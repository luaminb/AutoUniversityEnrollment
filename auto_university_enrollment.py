# The Sims 4 - Automatic University Enrollment for unplayed NPCs
# Requires Discover University and a Python 3.7-compatible TS4 runtime.

import services
import alarms
from away_actions.away_action_tracker import AwayActionTracker
import sims4.log
from careers.career_base import CareerBase
from careers.career_location import CareerLocation, CareerLocationServiceNpc
from careers.career_ops import CareerTimeOffReason
from date_and_time import create_time_span
from sims.aging.aging_mixin import AgingMixin
from sims.sim_info_types import Age
from sims.university.university_enums import EnrollmentStatus
from sims.university.university_tuning import University
from zone import Zone
from interactions.base.super_interaction import SuperInteraction
from interactions.context import InteractionContext, QueueInsertStrategy
import interactions.priority
from world.mailbox_owner_helper import MailboxOwnerHelper
import zone_types


logger = sims4.log.Logger('AutoUniversityEnrollment')
_PATCH_MARKER = '_auto_university_enrollment_patched'
_ZONE_PATCH_MARKER = '_auto_university_enrollment_zone_patched'
_CAREER_PATCH_MARKER = '_auto_university_enrollment_career_patched'
_CAREER_DRAMA_TIME_OFF_PATCH_MARKER = '_auto_university_enrollment_drama_time_off_patched'
_AWAY_ACTION_TRACKER_PATCH_MARKER = '_auto_university_enrollment_away_action_tracker_patched'
_CAREER_TONE_PATCH_MARKER = '_auto_university_enrollment_career_tone_patched'
_startup_sweep_completed = False


# Conservative mappings: only aspirations with a clear academic/career link
# receive a preferred major. All other aspirations retain random selection.
_ASPIRATION_MAJOR_MAP = (
    (('bestsellingauthor', 'writer', 'writing'), 'languageandliterature'),
    (('painterextraordinaire', 'artisticprodigy', 'painter'), 'fineart'),
    (('musicalgenius', 'actor', 'dramatic'), 'drama'),
    (('masterchef', 'mastermixologist', 'chef', 'mixologist'), 'culinaryarts'),
    (('computerwhiz', 'computer'), 'computerscience'),
    (('nerdbrain', 'scientist', 'science'), 'physics'),
    (('bodybuilder', 'freelancebotanist', 'botanist', 'fitness'), 'biology'),
    (('fabulouslywealthy', 'mansionbaron', 'business'), 'economics'),
    (('publicenemy', 'chiefofmischief', 'villain', 'criminal'), 'villainy'),
    (('archaeologyscholar', 'historian', 'history'), 'history'),
    (('friendofworld', 'socialbutterfly', 'communication'), 'communications'),
)


def _tuning_name(tuning):
    """Get a stable, lowercase identifier from a tuning instance."""
    if tuning is None:
        return ''

    try:
        name = getattr(tuning, '__name__', None)
        if name:
            return str(name).lower().replace('_', '').replace(' ', '')
    except Exception:
        pass

    try:
        name = getattr(tuning, 'name', None)
        if name:
            return str(name).lower().replace('_', '').replace(' ', '')
    except Exception:
        pass

    try:
        return str(tuning).lower().replace('_', '').replace(' ', '')
    except Exception:
        return ''


def _get_primary_aspiration_key(sim_info):
    """Read the Sim's primary aspiration without requiring a loaded Sim instance."""
    try:
        aspiration = getattr(sim_info, '_primary_aspiration', None)
        if aspiration is None:
            aspiration_tracker = getattr(sim_info, 'aspiration_tracker', None)
            if aspiration_tracker is not None:
                aspiration = getattr(aspiration_tracker, 'primary_aspiration', None)
        if aspiration is None:
            aspiration = getattr(sim_info, 'primary_aspiration', None)
        return _tuning_name(aspiration)
    except Exception as exc:
        logger.error('Could not read primary aspiration for Sim {}: {}', sim_info, exc)
        return ''


def _choose_major_for_aspiration(sim_info, majors):
    """Choose a matching tuned major, or use the game's random-major helper."""
    aspiration_key = _get_primary_aspiration_key(sim_info)

    if aspiration_key:
        for aspiration_tokens, major_token in _ASPIRATION_MAJOR_MAP:
            if any(token in aspiration_key for token in aspiration_tokens):
                for major in majors:
                    if major_token in _tuning_name(major):
                        logger.info(
                            'Aspiration-based major selected: Sim={} Aspiration={} Major={}',
                            sim_info, aspiration_key, major
                        )
                        return major

                logger.info(
                    'Preferred major {} for aspiration {} is not available in tuning; using random major.',
                    major_token, aspiration_key
                )
                break

    return University.choose_random_major()


def _has_completed_degree(tracker):
    """Use the public DegreeTracker history to detect any graduated major."""
    if tracker is None:
        return False
    try:
        previous_majors = getattr(tracker, 'previous_majors', None)
        if previous_majors:
            return True
    except Exception:
        pass
    try:
        return bool(getattr(tracker, '_previous_majors', ()))
    except Exception:
        return False


def _has_university_class_on_day(sim_info, target_time=None):
    """Check course slots on the work shift's date, using current time as schedule anchor."""
    try:
        career_tracker = getattr(sim_info, 'career_tracker', None)
        if career_tracker is None:
            return False
        careers = getattr(career_tracker, 'careers', {})
        career_values = careers.values() if hasattr(careers, 'values') else ()
        course_careers = tuple(c for c in career_values if getattr(c, 'is_course_slot', False))
        if not course_careers:
            logger.info('No UniversityCourseCareerSlot found for Sim {}', sim_info)
            return False

        # get_next_work_time interprets offset_time relative to sim_now, not
        # relative to the supplied work-shift end_time. Keep those two clocks
        # separate: the target date comes from the work shift, schedule scans
        # are anchored to the actual current game time.
        now = services.time_service().sim_now
        target = target_time if target_time is not None else now
        target_day = int(target.absolute_days())
        initial_offset = create_time_span(hours=-36)

        for course_career in course_careers:
            offset = initial_offset
            for _ in range(16):
                result = course_career.get_next_work_time(
                    offset_time=offset,
                    check_if_can_go_now=False,
                    consider_skipped_shifts=False,
                    ignore_pto=True
                )
                if not result or len(result) < 2:
                    break
                class_start = result[1]
                if class_start is None:
                    break
                class_day = int(class_start.absolute_days())
                if class_day == target_day:
                    logger.info('University class matches workday: Sim={} Day={} Slot={}',
                                sim_info, target_day, course_career)
                    return True
                if class_day > target_day:
                    break
                offset = (class_start - now) + create_time_span(minutes=1)
        logger.info('No university class on workday: Sim={} Day={}', sim_info, target_day)
        return False
    except Exception as exc:
        logger.error('Could not inspect university class schedule for Sim {}: {}', sim_info, exc)
        return False


def _has_active_university_enrollment(sim_info):
    """Return True for any Sim currently enrolled or on academic probation."""
    try:
        if sim_info is None:
            return False
        tracker = getattr(sim_info, 'degree_tracker', None)
        if tracker is None:
            return False
        return tracker.get_enrollment_status() in (
            EnrollmentStatus.ENROLLED,
            EnrollmentStatus.PROBATION
        )
    except Exception as exc:
        logger.error('Could not validate university enrollment for Sim {}: {}', sim_info, exc)
        return False


def _is_unplayed_npc_with_active_degree(sim_info):
    """Limit academic leave to NPCs in unplayed households with active enrollment."""
    try:
        if sim_info is None or not sim_info.is_npc:
            return False
        if sim_info.is_player_sim or sim_info.is_played_sim or sim_info.is_selectable:
            return False
        household = sim_info.household
        if household is None or household.is_player_household or household.is_played_household:
            return False
        tracker = sim_info.degree_tracker
        if tracker is None:
            return False
        return tracker.get_enrollment_status() in (EnrollmentStatus.ENROLLED, EnrollmentStatus.PROBATION)
    except Exception as exc:
        logger.error('Could not validate academic leave eligibility for Sim {}: {}', sim_info, exc)
        return False


def _prepare_academic_day_off(career):
    """Request paid academic leave before the Sim's work shift starts."""
    try:
        if getattr(career, 'is_course_slot', False) or getattr(career, '_at_work', False):
            return False
        if getattr(career, 'requested_day_off', False) or getattr(career, 'taking_day_off', False):
            return False
        sim_info = getattr(career, 'sim_info', None)
        if sim_info is None:
            sim_info = getattr(career, '_sim_info', None)
        if not _is_unplayed_npc_with_active_degree(sim_info):
            return False
        if not _has_university_class_on_day(sim_info, target_end_time):
            return False

        # FAKE_SICK uses the native paid-leave pipeline without deducting PTO.
        career.request_day_off(CareerTimeOffReason.FAKE_SICK)
        career._aue_academic_day_off = True
        logger.info('Academic paid day off requested: Sim={} Career={}', sim_info, career)
        return True
    except Exception as exc:
        logger.error('Could not request academic day off for career {}: {}', career, exc)
        return False


def _eligible_for_enrollment(sim_info):
    """Return True only for NPCs in households that have never been played."""
    if sim_info is None:
        return False

    try:
        if not sim_info.is_npc:
            return False
        if sim_info.is_player_sim or sim_info.is_played_sim:
            return False
        if sim_info.is_selectable:
            return False

        household = sim_info.household
        if household is None:
            return False
        if household.is_player_household or household.is_played_household:
            return False

        tracker = sim_info.degree_tracker
        if tracker is None:
            return False

        # Only enroll Sims with no current or previous university history.
        if tracker.get_enrollment_status() != EnrollmentStatus.NONE:
            return False
        if tracker.get_enrolled_major() is not None:
            return False
        if _has_completed_degree(tracker):
            return False
        if getattr(tracker, 'previous_courses', None) or getattr(tracker, '_previous_courses', ()):
            return False

        return True
    except Exception as exc:
        logger.error('Eligibility check failed for Sim {}: {}', sim_info, exc)
        return False


def _enroll_sim(sim_info):
    if not _eligible_for_enrollment(sim_info):
        return False

    tracker = sim_info.degree_tracker
    universities = tuple(University.ALL_UNIVERSITIES)
    majors = tuple(University.ALL_DEGREES)
    if not universities or not majors:
        logger.error('University tuning is empty; cannot enroll {}', sim_info)
        return False

    university = University.choose_random_university()
    major = _choose_major_for_aspiration(sim_info, majors)
    if university not in universities or major not in majors:
        logger.error('Random university/major selection returned an invalid tuning reference for {}', sim_info)
        return False

    try:
        # Follow the game's own Sim-template enrollment sequence.
        tracker.process_acceptance(send_telemetry=False)
        if not tracker.is_accepted_degree(university, major):
            tracker.set_accepted_degree(university, major)

        tracker.enroll(major, university, 4, [])

        status = tracker.get_enrollment_status()
        enrolled_major = tracker.get_enrolled_major()
        enrolled_university = tracker.get_university()
        if (status in (EnrollmentStatus.ENROLLED, EnrollmentStatus.PROBATION)
                and enrolled_major is not None and enrolled_university is not None):
            logger.info('Automatic enrollment succeeded: Sim={} University={} Major={}', sim_info, enrolled_university, enrolled_major)
            return True

        logger.error('Enrollment did not complete for Sim {}. Final status: {}', sim_info, status)
        return False
    except Exception as exc:
        logger.error('Automatic enrollment failed for Sim {}: {}', sim_info, exc)
        return False


def _enroll_existing_young_adults():
    """Run one global sweep after the first world zone is fully running."""
    global _startup_sweep_completed

    if _startup_sweep_completed:
        return

    try:
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            logger.error('SimInfoManager is unavailable; startup enrollment sweep postponed.')
            return

        sim_infos = tuple(sim_info_manager.get_all())
    except Exception as exc:
        logger.error('Could not retrieve existing SimInfo records: {}', exc)
        return

    # Mark complete only after obtaining the complete manager collection.
    _startup_sweep_completed = True
    checked = 0
    enrolled = 0

    for sim_info in sim_infos:
        try:
            if sim_info.age != Age.YOUNGADULT:
                continue
            checked += 1
            if _enroll_sim(sim_info):
                enrolled += 1
        except Exception as exc:
            # One malformed or unavailable Sim must not stop the remaining sweep.
            logger.error('Startup enrollment failed for Sim {}: {}', sim_info, exc)

    logger.info('Startup sweep finished. Young adults checked={} enrolled={}', checked, enrolled)



def _find_take_notes_tone(career):
    """Find the tuned university away action that represents Take Notes."""
    try:
        for tone in career.get_available_tones_gen():
            tone_name = _tuning_name(tone)
            if 'takenotes' in tone_name:
                return tone
    except Exception as exc:
        logger.error('Could not inspect university class tones for career {}: {}', career, exc)
    return None


# EA disables AwayActionTracker for every NPC. Temporarily permit it only
# during the one controlled application of the university Take Notes tone.
if not getattr(AwayActionTracker, _AWAY_ACTION_TRACKER_PATCH_MARKER, False):
    _original_is_sim_info_valid_to_run_away_actions = AwayActionTracker.is_sim_info_valid_to_run_away_actions

    def _auto_university_allow_scoped_npc_away_action(self):
        if getattr(self, '_aue_allow_university_take_notes', False):
            return True
        return _original_is_sim_info_valid_to_run_away_actions(self)

    AwayActionTracker.is_sim_info_valid_to_run_away_actions = _auto_university_allow_scoped_npc_away_action
    setattr(AwayActionTracker, _AWAY_ACTION_TRACKER_PATCH_MARKER, True)


if not getattr(CareerBase, _CAREER_TONE_PATCH_MARKER, False):
    _original_start_tones = CareerBase.start_tones

    def _auto_university_start_tones(self):
        sim_info = getattr(self, 'sim_info', None)
        if (getattr(self, 'is_course_slot', False)
                and _has_active_university_enrollment(sim_info)):
            tracker = getattr(sim_info, 'away_action_tracker', None)
            if tracker is None:
                logger.error('No AwayActionTracker for enrolled Sim {}', sim_info)
                return
            take_notes_tone = _find_take_notes_tone(self)
            if take_notes_tone is None:
                logger.error('Take Notes tone was not found for university course career {}', self)
                return

            try:
                tracker.add_on_away_action_started_callback(self._on_tone_started)
                tracker.add_on_away_action_ended_callback(self._on_tone_ended)
                tracker._aue_allow_university_take_notes = True
                try:
                    tracker.create_and_apply_away_action(take_notes_tone)
                finally:
                    tracker._aue_allow_university_take_notes = False
                logger.info(
                    'University class tone set to Take Notes: Sim={} Career={} Tone={}',
                    sim_info, self, take_notes_tone
                )
                return
            except Exception as exc:
                logger.error('Could not apply Take Notes tone for enrolled Sim {}: {}', sim_info, exc)
                return

        return _original_start_tones(self)

    CareerBase.start_tones = _auto_university_start_tones
    setattr(CareerBase, _CAREER_TONE_PATCH_MARKER, True)


if not getattr(CareerBase, _CAREER_DRAMA_TIME_OFF_PATCH_MARKER, False):
    _original_get_drama_node_time_off_reason = CareerBase._get_drama_node_time_off_reason

    def _auto_university_get_drama_node_time_off_reason(self, end_time=None):
        # Preserve every native drama-node decision first (holidays, events, etc.).
        # Resolve the shift end date exactly as the EA method does. Its
        # early-warning caller normally passes no argument.
        target_end_time = end_time
        if target_end_time is None:
            try:
                _, _, target_end_time = self.get_next_work_time()
            except Exception:
                target_end_time = None

        reason = _original_get_drama_node_time_off_reason(self, end_time)
        if reason != CareerTimeOffReason.NO_TIME_OFF:
            return reason

        try:
            # University course slots are class schedules, not work shifts.
            if getattr(self, 'is_course_slot', False):
                return CareerTimeOffReason.NO_TIME_OFF

            sim_info = getattr(self, 'sim_info', None)
            if sim_info is None:
                sim_info = getattr(self, '_sim_info', None)

            if not _has_active_university_enrollment(sim_info):
                return CareerTimeOffReason.NO_TIME_OFF

            # Match the workday being evaluated. Early-warning is scheduled
            # before the shift, so sim_now identifies the current workday.
            if not _has_university_class_on_day(sim_info, target_end_time):
                return CareerTimeOffReason.NO_TIME_OFF

            # Use the game's native paid absence reason. Unlike PTO this does
            # not consume the Sim's accrued time-off balance.
            self._aue_academic_day_off = True
            logger.info(
                'Academic day off supplied through native drama-node query: Sim={} Career={}',
                sim_info, self
            )
            return CareerTimeOffReason.FAKE_SICK
        except Exception as exc:
            logger.error(
                'Could not evaluate academic day off in drama-node query for career {}: {}',
                self, exc
            )
            return CareerTimeOffReason.NO_TIME_OFF

    CareerBase._get_drama_node_time_off_reason = _auto_university_get_drama_node_time_off_reason
    setattr(CareerBase, _CAREER_DRAMA_TIME_OFF_PATCH_MARKER, True)


_CAREER_ATTEND_WORK_PATCH_MARKER = '_auto_university_enrollment_attend_work_patched'

if not getattr(CareerBase, _CAREER_ATTEND_WORK_PATCH_MARKER, False):
    _original_attend_work = CareerBase.attend_work

    def _auto_university_attend_work(self, *args, **kwargs):
        # Final guard: evaluate the actual work-start call, not only the
        # earlier drama-node/early-warning query.
        if not getattr(self, 'is_course_slot', False):
            sim_info = getattr(self, 'sim_info', None)
            if sim_info is None:
                sim_info = getattr(self, '_sim_info', None)

            if _has_active_university_enrollment(sim_info):
                try:
                    now = services.time_service().sim_now
                    if _has_university_class_on_day(sim_info, now):
                        duration = getattr(self, '_current_work_duration', None)
                        if duration is None:
                            logger.error(
                                'Academic leave matched at attend_work, but shift duration is unavailable: Sim={} Career={}',
                                sim_info, self
                            )
                            # Do not send the Sim to work merely because the
                            # duration field was unavailable; suppress attendance.
                            self._aue_academic_day_off = True
                            return None

                        self._aue_academic_day_off = True
                        # NPCs do not receive the vanilla absent-shift payout.
                        # Played Sims do: their native end-work callback handles
                        # the FAKE_SICK paid absence, so never pay them here.
                        if getattr(sim_info, 'is_npc', False):
                            if not getattr(self, '_aue_academic_day_off_paid', False):
                                self.handle_career_loot(duration.in_hours())
                                self._aue_academic_day_off_paid = True
                        logger.info(
                            'Academic shift suppressed at attend_work; scheduled pay processed: Sim={} Career={} Hours={}',
                            sim_info, self, duration.in_hours()
                        )
                        return None
                except Exception as exc:
                    logger.error(
                        'Final academic leave check failed at attend_work for career {}: {}',
                        self, exc
                    )

        # Clear stale state on a later non-class workday.
        self._aue_academic_day_off = False
        self._aue_academic_day_off_paid = False
        return _original_attend_work(self, *args, **kwargs)

    CareerBase.attend_work = _auto_university_attend_work
    setattr(CareerBase, _CAREER_ATTEND_WORK_PATCH_MARKER, True)


if not getattr(CareerBase, _CAREER_PATCH_MARKER, False):
    _original_end_work_callback = CareerBase._end_work_callback

    def _auto_university_end_work_callback(self, alarm):
        # EA skips career loot for NPCs who did not attend the rabbit hole.
        # Pay the scheduled duration once, while retaining the native session
        # end logic and its non-PTO FAKE_SICK time-off classification.
        sim_info = getattr(self, '_sim_info', None)
        if (getattr(self, '_aue_academic_day_off', False)
                and not getattr(self, '_aue_academic_day_off_paid', False)
                and sim_info is not None and sim_info.is_npc
                and not getattr(self, 'currently_at_work', False)):
            try:
                duration = getattr(self, '_current_work_duration', None)
                if duration is not None:
                    self.handle_career_loot(duration.in_hours())
                    self._aue_academic_day_off_paid = True
                    logger.info(
                        'Paid NPC academic day off: Sim={} Career={} Hours={}',
                        sim_info, self, duration.in_hours()
                    )
            except Exception as exc:
                logger.error('Could not pay NPC academic leave for career {}: {}', self, exc)
        result = _original_end_work_callback(self, alarm)
        self._aue_academic_day_off = False
        self._aue_academic_day_off_paid = False
        return result

    CareerBase._end_work_callback = _auto_university_end_work_callback
    setattr(CareerBase, _CAREER_PATCH_MARKER, True)



# NPC work dispatch has two EA paths: the standard career location and the
# service-NPC specialization. Both must respect the academic leave marker.
_LOCATION_PATCH_MARKER = '_auto_university_enrollment_npc_dispatch_patched'


def _patch_npc_dispatch(location_class):
    if getattr(location_class, _LOCATION_PATCH_MARKER, False):
        return
    original = location_class.on_npc_start_work

    def _auto_university_on_npc_start_work(self, *args, **kwargs):
        career = getattr(self, '_career', None)
        if career is not None and getattr(career, '_aue_academic_day_off', False):
            logger.info(
                'NPC work dispatch suppressed for academic leave: Sim={} Career={} Location={}',
                getattr(career, 'sim_info', None), career, location_class
            )
            return None
        return original(self, *args, **kwargs)

    location_class.on_npc_start_work = _auto_university_on_npc_start_work
    setattr(location_class, _LOCATION_PATCH_MARKER, True)


_patch_npc_dispatch(CareerLocation)
_patch_npc_dispatch(CareerLocationServiceNpc)

if not getattr(Zone, _ZONE_PATCH_MARKER, False):
    _original_do_zone_spin_up = Zone.do_zone_spin_up

    def _auto_university_zone_spin_up(self, household_id, active_sim_id, *args, **kwargs):
        result = _original_do_zone_spin_up(self, household_id, active_sim_id, *args, **kwargs)

        def _run_sweep():
            try:
                _enroll_existing_young_adults()
                _schedule_loaded_university_classes()
                _inject_preparation_affordance_into_mailboxes()
            except Exception as exc:
                logger.error('Unexpected startup sweep error: {}', exc)

        # RUNNING ensures household and SimInfo services are available.
        self.register_callback(zone_types.ZoneState.RUNNING, _run_sweep)
        return result

    Zone.do_zone_spin_up = _auto_university_zone_spin_up
    setattr(Zone, _ZONE_PATCH_MARKER, True)


if not getattr(AgingMixin, _PATCH_MARKER, False):
    _original_change_age = AgingMixin.change_age

    def _auto_university_change_age(self, new_age, current_age, *args, **kwargs):
        result = _original_change_age(self, new_age, current_age, *args, **kwargs)
        if current_age == Age.TEEN and new_age == Age.YOUNGADULT:
            try:
                _enroll_sim(self)
            except Exception as exc:
                # Never allow a mod-side enrollment error to interrupt aging.
                logger.error('Unexpected error while enrolling aged-up Sim {}: {}', self, exc)
        return result

    AgingMixin.change_age = _auto_university_change_age
    setattr(AgingMixin, _PATCH_MARKER, True)
    logger.info('Automatic University Enrollment patch loaded.')


# ---------------------------------------------------------------------------
# Independent residential pre-class preparation interaction (v0.20)
# ---------------------------------------------------------------------------

_AUE_PREPARATION_INTERACTION_ID = 0xA2E731B4C8D91057
_AUE_PREPARATION_ALARM_MARKER = '_aue_independent_preparation_alarm'
_AUE_PREPARATION_PATCH_MARKER = '_aue_independent_preparation_career_start_patched'


class SePrepararParaAulaInteraction(SuperInteraction):
    """Non-tuned pie-menu interaction exposed dynamically on mailbox objects."""

    INSTANCE_SUBCLASSES_ONLY = False
    guid64 = _AUE_PREPARATION_INTERACTION_ID

    @classmethod
    def get_name(cls, *args, **kwargs):
        from sims4.localization import LocalizationHelperTuning
        return LocalizationHelperTuning.get_raw_text('Se Preparar para a Aula')

    @classmethod
    def _test(cls, target, context, **kwargs):
        from event_testing.results import TestResult
        try:
            mailbox_tags = tuple(getattr(MailboxOwnerHelper, 'MAILBOX_TAGS', ()) or ())
            target_tags = tuple(target.get_tags())
            if any(tag in target_tags for tag in mailbox_tags):
                return TestResult.TRUE
        except Exception:
            pass
        return TestResult(False, 'This interaction is only available on mailboxes.')

    def _run_interaction_gen(self, timeline):
        logger.info(
            'Independent class preparation interaction started: Sim={} Mailbox={}',
            getattr(self, 'sim', None), getattr(self, 'target', None)
        )
        return True


def _inject_preparation_affordance_into_mailboxes():
    """Append the custom interaction to live-object affordance results."""
    try:
        from objects.game_object import GameObject
        for cls in GameObject.__mro__:
            descriptor = cls.__dict__.get('super_affordances')
            if descriptor is not None:
                break
        else:
            logger.error('Could not locate GameObject.super_affordances descriptor.')
            return False

        marker = '_aue_preparation_affordance_hooked'
        if getattr(GameObject, marker, False):
            return True

        def _aue_super_affordances(self, *args, **kwargs):
            original = descriptor.__get__(self, type(self))
            affordances = tuple(original(*args, **kwargs))
            if any(getattr(item, 'guid64', None) == _AUE_PREPARATION_INTERACTION_ID
                   for item in affordances):
                return affordances
            try:
                if any(tag in tuple(self.get_tags())
                       for tag in tuple(getattr(MailboxOwnerHelper, 'MAILBOX_TAGS', ()) or ())):
                    return affordances + (SePrepararParaAulaInteraction,)
            except Exception:
                pass
            return affordances

        # Patch the class that owns the flexmethod, not a tuning instance.
        owner = cls
        owner.super_affordances = _aue_super_affordances
        setattr(GameObject, marker, True)
        logger.info('Independent preparation interaction injected through GameObject.super_affordances.')
        return True
    except Exception as exc:
        logger.error('Could not hook mailbox affordances: {}', exc)
        return False


def _aue_get_home_mailbox(sim_info):
    """Return the mailbox on the Sim household's currently loaded home lot."""
    try:
        household = getattr(sim_info, 'household', None)
        if household is None:
            return None
        home_zone_id = getattr(household, 'home_zone_id', None)
        current_zone_id = services.current_zone_id()
        if not home_zone_id or home_zone_id != current_zone_id:
            return None
        mailbox_tags = tuple(getattr(MailboxOwnerHelper, 'MAILBOX_TAGS', ()) or ())
        if not mailbox_tags:
            logger.error('Mailbox tags unavailable for independent preparation.')
            return None
        object_manager = services.object_manager()
        if object_manager is None:
            return None
        for mailbox in object_manager.get_objects_with_tags_gen(*mailbox_tags):
            if getattr(mailbox, 'zone_id', current_zone_id) == current_zone_id:
                return mailbox
    except Exception as exc:
        logger.error('Could not locate home mailbox for class preparation: {}', exc)
    return None


def _aue_get_preparation_affordance():
    # This is a script-defined SuperInteraction, not an XML tuning resource.
    return SePrepararParaAulaInteraction


def _inject_preparation_affordance_into_mailboxes():
    """Expose the independent action on mailbox tuning for manual testing."""
    try:
        affordance = _aue_get_preparation_affordance()
        if affordance is None:
            logger.error('Preparation affordance is not loaded; mailbox injection skipped.')
            return False
        object_manager = services.object_manager()
        if object_manager is None:
            return False
        mailbox_tags = tuple(getattr(MailboxOwnerHelper, 'MAILBOX_TAGS', ()) or ())
        count = 0
        for mailbox in object_manager.get_objects_with_tags_gen(*mailbox_tags):
            tuning_class = type(mailbox)
            current = tuple(getattr(tuning_class, '_super_affordances', ()) or ())
            if affordance not in current:
                tuning_class._super_affordances = current + (affordance,)
                count += 1
        if count:
            logger.info('Injected independent preparation interaction into {} mailbox tuning classes.', count)
        return True
    except Exception as exc:
        logger.error('Could not inject preparation affordance into mailboxes: {}', exc)
        return False


def _aue_push_independent_preparation(course_career):
    """Push the new action directly; do not call EA's arrive-early affordance."""
    try:
        sim_info = getattr(course_career, 'sim_info', None)
        if sim_info is None:
            sim_info = getattr(course_career, '_sim_info', None)
        if not _has_active_university_enrollment(sim_info):
            return False
        _inject_preparation_affordance_into_mailboxes()
        mailbox = _aue_get_home_mailbox(sim_info)
        if mailbox is None:
            logger.info('Preparation time reached, but Sim is not on the home lot: Sim={}', sim_info)
            return False
        sim = course_career._get_sim()
        affordance = _aue_get_preparation_affordance()
        if sim is None or affordance is None:
            logger.error('Cannot push preparation action: Sim={} Affordance={}', sim, affordance)
            return False
        queue = getattr(sim, 'queue', None)
        if queue is not None and queue.has_duplicate_super_affordance(affordance, sim, mailbox):
            return True
        context = InteractionContext(
            sim,
            InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT,
            interactions.priority.Priority.High,
            insert_strategy=QueueInsertStrategy.FIRST
        )
        result = sim.push_super_affordance(affordance, mailbox, context)
        logger.info(
            'Independent preparation action pushed: Sim={} Course={} Mailbox={} Result={}',
            sim_info, course_career, mailbox, result
        )
        return bool(result is not False)
    except Exception as exc:
        logger.error('Could not push independent preparation action for {}: {}', course_career, exc)
        return False


def _aue_schedule_preparation_alarm(course_career, offset_hours=0):
    """Schedule the independent action exactly one hour before the next class."""
    try:
        sim_info = getattr(course_career, 'sim_info', None)
        if sim_info is None:
            sim_info = getattr(course_career, '_sim_info', None)
        if not _has_active_university_enrollment(sim_info):
            return False

        old_handle = getattr(course_career, _AUE_PREPARATION_ALARM_MARKER, None)
        if old_handle is not None:
            try:
                alarms.cancel_alarm(old_handle)
            except Exception:
                pass

        offset = create_time_span(hours=offset_hours) if offset_hours else None
        result = course_career.get_next_work_time(
            offset_time=offset,
            check_if_can_go_now=False,
            consider_skipped_shifts=False,
            ignore_pto=True
        )
        time_until_class = result[0] if result else None
        if time_until_class is None:
            return False

        delay = time_until_class + (offset if offset is not None else create_time_span()) - create_time_span(hours=1)
        if delay < create_time_span():
            delay = create_time_span()

        handle = alarms.add_alarm(
            course_career,
            delay,
            lambda _: _aue_preparation_alarm_callback(course_career),
            repeating=False
        )
        setattr(course_career, _AUE_PREPARATION_ALARM_MARKER, handle)
        logger.info(
            'Independent one-hour preparation alarm scheduled: Sim={} Course={} DelayMinutes={}',
            sim_info, course_career, delay.in_minutes()
        )
        return True
    except Exception as exc:
        logger.error('Could not schedule independent preparation alarm for {}: {}', course_career, exc)
        return False


def _aue_preparation_alarm_callback(course_career):
    try:
        setattr(course_career, _AUE_PREPARATION_ALARM_MARKER, None)
        _aue_push_independent_preparation(course_career)
        _aue_schedule_preparation_alarm(course_career, offset_hours=6)
    except Exception as exc:
        logger.error('Independent preparation alarm callback failed: {}', exc)


def _schedule_loaded_university_classes():
    try:
        manager = services.sim_info_manager()
        if manager is None:
            return
        for sim_info in manager.get_all():
            tracker = getattr(sim_info, 'career_tracker', None)
            if tracker is None:
                continue
            careers = getattr(tracker, 'careers', {})
            values = careers.values() if hasattr(careers, 'values') else ()
            for career in values:
                if getattr(career, 'is_course_slot', False):
                    _aue_schedule_preparation_alarm(career)
    except Exception as exc:
        logger.error('Could not schedule independent university preparation alarms: {}', exc)


if not getattr(CareerBase, _AUE_PREPARATION_PATCH_MARKER, False):
    _aue_original_career_start_for_preparation = CareerBase.career_start

    def _aue_career_start_with_independent_preparation(self, *args, **kwargs):
        result = _aue_original_career_start_for_preparation(self, *args, **kwargs)
        if getattr(self, 'is_course_slot', False):
            _aue_schedule_preparation_alarm(self)
        return result

    CareerBase.career_start = _aue_career_start_with_independent_preparation
    setattr(CareerBase, _AUE_PREPARATION_PATCH_MARKER, True)

logger.info('Independent Se Preparar para a Aula interaction loaded.')

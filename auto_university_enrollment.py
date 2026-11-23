# The Sims 4 - Automatic University Enrollment for unplayed NPCs
# Requires Discover University and a Python 3.7-compatible TS4 runtime.

import services
import sims4.log
from careers.career_base import CareerBase
from careers.career_location import CareerLocation
from careers.career_ops import CareerTimeOffReason
from date_and_time import create_time_span
from sims.aging.aging_mixin import AgingMixin
from sims.sim_info_types import Age
from sims.university.university_enums import EnrollmentStatus
from sims.university.university_tuning import University
from zone import Zone
import zone_types


logger = sims4.log.Logger('AutoUniversityEnrollment')
_PATCH_MARKER = '_auto_university_enrollment_patched'
_ZONE_PATCH_MARKER = '_auto_university_enrollment_zone_patched'
_CAREER_PATCH_MARKER = '_auto_university_enrollment_career_patched'
_CAREER_LOCATION_PATCH_MARKER = '_auto_university_enrollment_career_location_patched'
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


def _has_university_class_on_day(sim_info, reference_time=None):
    """Check active UniversityCourseCareerSlot schedules for a given day."""
    try:
        career_tracker = getattr(sim_info, 'career_tracker', None)
        if career_tracker is None:
            return False
        careers = getattr(career_tracker, 'careers', {})
        career_values = careers.values() if hasattr(careers, 'values') else ()
        course_careers = tuple(c for c in career_values if getattr(c, 'is_course_slot', False))
        if not course_careers:
            return False

        now = reference_time if reference_time is not None else services.time_service().sim_now
        today = int(now.absolute_days())
        initial_offset = create_time_span(hours=-36)

        for course_career in course_careers:
            offset = initial_offset
            for _ in range(12):
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
                if class_day == today:
                    return True
                if class_day > today:
                    break
                offset = (class_start - now) + create_time_span(minutes=1)
        return False
    except Exception as exc:
        logger.error('Could not inspect university class schedule for Sim {}: {}', sim_info, exc)
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
        if not _has_university_class_on_day(sim_info):
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

        tracker.enroll(major, university, 3, [])

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


if not getattr(CareerBase, _CAREER_PATCH_MARKER, False):
    _original_start_work_callback = CareerBase._start_work_callback

    def _auto_university_start_work_callback(self, scheduler, alarm_data, extra_data):
        self._aue_academic_day_off = False
        try:
            _prepare_academic_day_off(self)
        except Exception as exc:
            logger.error('Unexpected academic leave error for career {}: {}', self, exc)
        return _original_start_work_callback(self, scheduler, alarm_data, extra_data)

    CareerBase._start_work_callback = _auto_university_start_work_callback
    setattr(CareerBase, _CAREER_PATCH_MARKER, True)


if not getattr(CareerLocation, _CAREER_LOCATION_PATCH_MARKER, False):
    _original_on_npc_start_work = CareerLocation.on_npc_start_work

    def _auto_university_npc_start_work(self):
        career = getattr(self, '_career', None)
        if career is not None and getattr(career, '_aue_academic_day_off', False):
            return
        return _original_on_npc_start_work(self)

    CareerLocation.on_npc_start_work = _auto_university_npc_start_work
    setattr(CareerLocation, _CAREER_LOCATION_PATCH_MARKER, True)


if not getattr(Zone, _ZONE_PATCH_MARKER, False):
    _original_do_zone_spin_up = Zone.do_zone_spin_up

    def _auto_university_zone_spin_up(self, household_id, active_sim_id, *args, **kwargs):
        result = _original_do_zone_spin_up(self, household_id, active_sim_id, *args, **kwargs)

        def _run_sweep():
            try:
                _enroll_existing_young_adults()
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

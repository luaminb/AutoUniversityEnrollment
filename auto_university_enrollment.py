# The Sims 4 - Automatic University Enrollment for unplayed NPCs
# Requires Discover University and a Python 3.7-compatible TS4 runtime.

import sims4.log
from sims.aging.aging_mixin import AgingMixin
from sims.sim_info_types import Age
from sims.university.university_enums import EnrollmentStatus
from sims.university.university_tuning import University


logger = sims4.log.Logger('AutoUniversityEnrollment')
_PATCH_MARKER = '_auto_university_enrollment_patched'


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
        if getattr(tracker, '_previous_majors', ()):
            return False
        if getattr(tracker, '_previous_courses', ()):
            return False

        return True
    except Exception as exc:
        logger.error('Eligibility check failed for Sim {}: {}', sim_info, exc)
        return False


def _enroll_sim(sim_info):
    if not _eligible_for_enrollment(sim_info):
        return False

    tracker = sim_info.degree_tracker
    # Use the same selection helpers called by the game's native Sim template.
    universities = tuple(University.ALL_UNIVERSITIES)
    majors = tuple(University.ALL_DEGREES)
    if not universities or not majors:
        logger.error('University tuning is empty; cannot enroll {}', sim_info)
        return False

    university = University.choose_random_university()
    major = University.choose_random_major()
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

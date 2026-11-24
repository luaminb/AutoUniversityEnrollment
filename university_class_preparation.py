# The Sims 4 - University Class Preparation (standalone mod)
# Requires Discover University and XML Injector 4.2+.
# Runtime target: The Sims 4 Python 3.7.

import services
import sims4.log
from date_and_time import create_time_span
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.context import InteractionContext, QueueInsertStrategy
import interactions.priority
from world.mailbox_owner_helper import MailboxOwnerHelper

logger = sims4.log.Logger('UniversityClassPreparation')

INTERACTION_ID = 11368423882965899103
PATCH_MARKER = '_university_class_preparation_early_warning_patched'


class SePrepararParaAulaInteraction(ImmediateSuperInteraction):
    """Routes the Sim to the injected mailbox interaction and waits for class."""

    @classmethod
    def _test(cls, target, context, **kwargs):
        from event_testing.results import TestResult
        if target is None:
            return TestResult(False, 'A mailbox target is required.')
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        import elements
        import element_utils

        # The tuned object interaction routes the Sim to the mailbox before
        # this generator runs. Keep the native interaction lifecycle intact.
        yield from super(SePrepararParaAulaInteraction, self)._run_interaction_gen(timeline)

        sim = getattr(self, 'sim', None)
        sim_info = getattr(sim, 'sim_info', None)
        delay = _time_until_next_class(sim_info)
        logger.info('Class preparation interaction started: Sim={} target={} delay={}',
                    sim, getattr(self, 'target', None), delay)

        if delay is not None and delay > create_time_span():
            yield from element_utils.run_child(timeline, elements.SleepElement(delay))

        logger.info('Class preparation wait completed: Sim={}', sim)
        return True


def _time_until_next_class(sim_info):
    """Return the soonest positive delay among the Sim's enrolled course slots."""
    try:
        career_tracker = getattr(sim_info, 'career_tracker', None)
        if career_tracker is None:
            return None
        careers = getattr(career_tracker, 'careers', {})
        values = careers.values() if hasattr(careers, 'values') else ()
        delays = []
        for career in values:
            if not getattr(career, 'is_course_slot', False):
                continue
            result = career.get_next_work_time(
                check_if_can_go_now=False,
                consider_skipped_shifts=False,
                ignore_pto=True
            )
            delay = result[0] if result and len(result) else None
            if delay is not None and delay > create_time_span():
                delays.append(delay)
        return min(delays) if delays else None
    except Exception as exc:
        logger.error('Could not calculate next class delay for {}: {}', sim_info, exc)
        return None


def _home_mailbox(sim_info):
    """Find a mailbox only when the Sim is on their currently loaded home lot."""
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
            logger.error('Mailbox tags unavailable; cannot queue class preparation.')
            return None
        object_manager = services.object_manager()
        if object_manager is None:
            return None
        for mailbox in object_manager.get_objects_with_tags_gen(*mailbox_tags):
            if getattr(mailbox, 'zone_id', current_zone_id) == current_zone_id:
                return mailbox
    except Exception as exc:
        logger.error('Could not locate the home mailbox: {}', exc)
    return None


def _push_preparation_interaction(course_career, mailbox):
    try:
        sim = course_career._get_sim()
        if sim is None:
            return False
        from sims4.resources import Types
        manager = services.get_instance_manager(Types.INTERACTION)
        affordance = manager.get(INTERACTION_ID) if manager is not None else None
        if affordance is None:
            logger.error('Tuned class-preparation affordance {} is not loaded.', INTERACTION_ID)
            return False

        queue = getattr(sim, 'queue', None)
        if queue is not None and queue.has_duplicate_super_affordance(affordance, mailbox, sim):
            return True

        context = InteractionContext(
            sim,
            InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT,
            interactions.priority.Priority.High,
            insert_strategy=QueueInsertStrategy.FIRST
        )
        result = sim.push_super_affordance(affordance, mailbox, context)
        logger.info('Queued class preparation: Sim={} mailbox={} result={}', sim, mailbox, result)
        return bool(result)
    except Exception as exc:
        logger.error('Could not queue class preparation: {}', exc)
        return False


def _install_early_warning_hook():
    """Use EA's one-hour university warning path; do not create a parallel alarm."""
    try:
        from sims.university.university_career_tuning import UniversityCourseCareerSlot
        if getattr(UniversityCourseCareerSlot, PATCH_MARKER, False):
            return True

        original = UniversityCourseCareerSlot.go_to_work_early

        def _university_class_preparation_go_to_work_early(self, *args, **kwargs):
            try:
                sim = self._get_sim()
                sim_info = getattr(sim, 'sim_info', None)
                mailbox = _home_mailbox(sim_info)
                if mailbox is not None and _push_preparation_interaction(self, mailbox):
                    return
            except Exception as exc:
                logger.error('Early-warning preparation hook failed; using EA behavior: {}', exc)
            return original(self, *args, **kwargs)

        UniversityCourseCareerSlot.go_to_work_early = _university_class_preparation_go_to_work_early
        setattr(UniversityCourseCareerSlot, PATCH_MARKER, True)
        logger.info('University one-hour early-warning hook installed.')
        return True
    except Exception as exc:
        logger.error('Could not install university early-warning hook: {}', exc)
        return False


_install_early_warning_hook()
logger.info('University Class Preparation standalone mod loaded.')

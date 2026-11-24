# University Class Preparation - standalone Sims 4 mod
# Requires Discover University and XML Injector v2+.

import services
import sims4.log
import interactions.priority
import elements
import element_utils
import zone_types
from date_and_time import create_time_span
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.context import InteractionContext, QueueInsertStrategy
from sims.university.university_career_tuning import UniversityCourseCareerSlot
from world.mailbox_owner_helper import MailboxOwnerHelper

logger = sims4.log.Logger('UniversityClassPreparation')
_INTERACTION_ID = 11368423882965899103
_PATCH_MARKER = '_ucp_go_to_work_early_patched'

class SePrepararParaAulaInteraction(ImmediateSuperInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        from event_testing.results import TestResult
        if target is not None:
            return TestResult.TRUE
        return TestResult(False, 'A mailbox target is required.')

    def _run_interaction_gen(self, timeline):
        yield from super()._run_interaction_gen(timeline)
        sim = getattr(self, 'sim', None)
        wait_time = _ucp_time_until_next_class(getattr(sim, 'sim_info', None))
        logger.info('Preparation interaction started: Sim={} Wait={}', sim, wait_time)
        if wait_time is not None and wait_time > create_time_span():
            yield from element_utils.run_child(timeline, elements.SleepElement(wait_time))
        logger.info('Preparation interaction finished: Sim={}', sim)
        return True

def _ucp_time_until_next_class(sim_info):
    try:
        tracker = getattr(sim_info, 'career_tracker', None)
        careers = getattr(tracker, 'careers', {}) if tracker is not None else {}
        delays = []
        for career in careers.values() if hasattr(careers, 'values') else ():
            if not getattr(career, 'is_course_slot', False):
                continue
            result = career.get_next_work_time(check_if_can_go_now=False, consider_skipped_shifts=False, ignore_pto=True)
            delay = result[0] if result else None
            if delay is not None and delay > create_time_span():
                delays.append(delay)
        return min(delays) if delays else None
    except Exception as exc:
        logger.error('Could not calculate next class time for {}: {}', sim_info, exc)
        return None

def _ucp_home_mailbox(sim_info):
    try:
        household = getattr(sim_info, 'household', None)
        home_zone_id = getattr(household, 'home_zone_id', None) if household is not None else None
        current_zone_id = services.current_zone_id()
        if not home_zone_id or home_zone_id != current_zone_id:
            return None
        tags = tuple(getattr(MailboxOwnerHelper, 'MAILBOX_TAGS', ()) or ())
        manager = services.object_manager()
        if not tags or manager is None:
            return None
        for mailbox in manager.get_objects_with_tags_gen(*tags):
            if getattr(mailbox, 'zone_id', current_zone_id) == current_zone_id:
                return mailbox
    except Exception as exc:
        logger.error('Could not find home mailbox: {}', exc)
    return None

def _ucp_affordance():
    try:
        from sims4.resources import Types
        manager = services.get_instance_manager(Types.INTERACTION)
        return manager.get(_INTERACTION_ID) if manager is not None else None
    except Exception as exc:
        logger.error('Could not resolve preparation affordance: {}', exc)
        return None

def _ucp_queue_interaction(career, mailbox):
    try:
        sim = career._get_sim()
        affordance = _ucp_affordance()
        if sim is None or affordance is None:
            logger.error('Preparation affordance unavailable: Sim={} affordance={}', sim, affordance)
            return False
        queue = getattr(sim, 'queue', None)
        if queue is not None and queue.has_duplicate_super_affordance(affordance, mailbox, sim):
            return True
        context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.FIRST)
        result = sim.push_super_affordance(affordance, mailbox, context)
        logger.info('Preparation interaction queued: Sim={} Mailbox={} Result={}', sim, mailbox, result)
        return bool(result)
    except Exception as exc:
        logger.error('Could not queue preparation interaction: {}', exc)
        return False

def _ucp_go_to_work_early(self, *args, **kwargs):
    try:
        sim_info = getattr(self, 'sim_info', None) or getattr(self, '_sim_info', None)
        mailbox = _ucp_home_mailbox(sim_info)
        if mailbox is not None and _ucp_queue_interaction(self, mailbox):
            return
    except Exception as exc:
        logger.error('Automatic home preparation failed; using EA behavior: {}', exc)
    return _ucp_original_go_to_work_early(self, *args, **kwargs)

if not getattr(UniversityCourseCareerSlot, _PATCH_MARKER, False):
    _ucp_original_go_to_work_early = UniversityCourseCareerSlot.go_to_work_early
    UniversityCourseCareerSlot.go_to_work_early = _ucp_go_to_work_early
    setattr(UniversityCourseCareerSlot, _PATCH_MARKER, True)
    logger.info('University class one-hour warning hook installed.')

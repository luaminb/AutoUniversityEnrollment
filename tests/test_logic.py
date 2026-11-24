import importlib.util
import pathlib
import sys
import types
import unittest

class FakeLogger:
    def __init__(self, name): self.name = name
    def info(self, *args): pass
    def error(self, *args): pass

class FakeTracker:
    def __init__(self, status=0, previous_majors=None, previous_courses=None):
        self.status=status; self._previous_majors=previous_majors or []; self._previous_courses=previous_courses or []
        self.accepted=set(); self.major=None; self.university=None
    def get_enrollment_status(self): return self.status
    def get_enrolled_major(self): return self.major if self.status in (1,3) else None
    def get_university(self): return self.university
    def process_acceptance(self, send_telemetry=False): assert send_telemetry is False
    def is_accepted_degree(self, university, major): return (university,major) in self.accepted
    def set_accepted_degree(self, university, major): self.accepted.add((university,major))
    def enroll(self, major, university, course_count, courses):
        self.major=major; self.university=university; self.course_count=course_count; self.courses=courses; self.status=1

class FakeAgingMixin:
    def change_age(self,new_age,current_age): self.last_age_change=(new_age,current_age); return 'age-change-result'

class FakeTone:
    def __init__(self, name): self.__name__=name

class FakeAwayActionTracker:
    def __init__(self):
        self._aue_allow_university_take_notes=False
        self.current_away_action=None
        self.started_callbacks=[]
        self.ended_callbacks=[]
        self.valid_during_apply=None
    def is_sim_info_valid_to_run_away_actions(self): return False
    def add_on_away_action_started_callback(self, callback): self.started_callbacks.append(callback)
    def add_on_away_action_ended_callback(self, callback): self.ended_callbacks.append(callback)
    def create_and_apply_away_action(self, tone):
        self.valid_during_apply=self.is_sim_info_valid_to_run_away_actions()
        if not self.valid_during_apply: return
        self.current_away_action=tone

class FakeUniversityCourseCareerSlot:
    _aue_home_early_class_patched=False
    def can_work_early(self): return False
    def go_to_work_early(self): self.original_early_called=True
    def _get_sim(self): return self.sim_instance

class FakeMailbox:
    zone_id=77

class FakeSimInstance:
    def __init__(self):
        self.queue=types.SimpleNamespace(has_duplicate_super_affordance=lambda *args: False)
        self.pushed=[]
    def push_super_affordance(self, *args, **kwargs): self.pushed.append((args,kwargs))

class FakeInteractionContext:
    SOURCE_SCRIPT_WITH_USER_INTENT='SCRIPT'
    def __init__(self,*args,**kwargs): self.args=args; self.kwargs=kwargs

class FakeCareerBase:
    def request_day_off(self, reason): self.requested_day_off_reason=reason
    def start_tones(self): self.original_start_tones_called=True
    def get_available_tones_gen(self): return iter(getattr(self, 'available_tones', ()))
    def _on_tone_started(self, tone): self.started_tone=tone
    def _on_tone_ended(self, tone): self.ended_tone=tone
    def handle_career_loot(self, hours): self.paid_hours=hours
    def attend_work(self): self.original_attend_work_called=True; return 'attend-work-result'
    def _get_drama_node_time_off_reason(self, end_time=None):
        return 'NO_TIME_OFF'
    def early_warning_callback(self):
        self.original_early_warning_called=True
        reason=self._get_drama_node_time_off_reason()
        if reason != 'NO_TIME_OFF': self.requested_day_off_reason=reason
        return 'early-warning-result'
    def _start_work_callback(self, scheduler, alarm_data, extra_data):
        self.original_start_called=True
        return 'career-start-result'
    def _end_work_callback(self, alarm):
        self.original_end_called=True
        return 'career-end-result'

class FakeCareerLocation:
    def on_npc_start_work(self):
        self.original_npc_start_called=True
        return 'npc-start-result'


class FakeCareerLocationServiceNpc(FakeCareerLocation):
    pass

class FakeTimeSpan:
    def __init__(self, minutes=0): self.minutes=minutes
    def __add__(self, other): return FakeTimeSpan(self.minutes+other.minutes)
    def __le__(self, other): return self.minutes <= other.minutes
    def in_hours(self): return self.minutes/60.0

class FakeDateTime:
    def __init__(self, day): self.day=day
    def absolute_days(self): return self.day
    def __sub__(self, other): return FakeTimeSpan((self.day-other.day)*1440)
    def __add__(self, span): return FakeDateTime(self.day + span.minutes/1440)

class FakeCourseCareer:
    is_course_slot=True
    def __init__(self, day): self.day=day
    def get_next_work_time(self, **kwargs): return (None, FakeDateTime(self.day), None)

class FakeSim(FakeAgingMixin):
    def __init__(self, npc=True, player=False, played=False, selectable=False, tracker=None, household=True, age=4, aspiration=None):
        self.is_npc=npc; self.is_player_sim=player; self.is_played_sim=played; self.is_selectable=selectable; self.age=age
        self.household=types.SimpleNamespace(is_player_household=player,is_played_household=played,home_zone_id=77) if household else None
        self.degree_tracker=tracker or FakeTracker(); self._primary_aspiration=aspiration
        self.away_action_tracker=FakeAwayActionTracker()
        self.career_tracker=types.SimpleNamespace(careers={})

def load_mod():
    sims4=types.ModuleType('sims4'); sims4.log=types.SimpleNamespace(Logger=FakeLogger)
    services=types.ModuleType('services'); services.sim_info_manager=lambda: None
    services.current_zone_id=lambda: 77
    services.object_manager=lambda: types.SimpleNamespace(get_objects_with_tags_gen=lambda *tags: iter([FakeMailbox()]))
    services.time_service=lambda: types.SimpleNamespace(sim_now=FakeDateTime(10))
    careers=types.ModuleType('careers'); careers.__path__=[]
    away_actions=types.ModuleType('away_actions'); away_actions.__path__=[]
    away_action_tracker=types.ModuleType('away_actions.away_action_tracker')
    away_action_tracker.AwayActionTracker=FakeAwayActionTracker
    career_base=types.ModuleType('careers.career_base'); career_base.CareerBase=FakeCareerBase
    career_location=types.ModuleType('careers.career_location'); career_location.CareerLocation=FakeCareerLocation
    career_location.CareerLocationServiceNpc=FakeCareerLocationServiceNpc
    career_ops=types.ModuleType('careers.career_ops'); career_ops.CareerTimeOffReason=types.SimpleNamespace(NO_TIME_OFF='NO_TIME_OFF',FAKE_SICK='FAKE_SICK')
    date_and_time=types.ModuleType('date_and_time'); date_and_time.create_time_span=lambda hours=0, minutes=0: FakeTimeSpan(hours*60+minutes)
    university_career=types.ModuleType('sims.university.university_career_tuning')
    university_career.UniversityCourseCareerSlot=FakeUniversityCourseCareerSlot
    mailbox_helper=types.ModuleType('world.mailbox_owner_helper')
    mailbox_helper.MailboxOwnerHelper=type('MailboxOwnerHelper',(),{'MAILBOX_TAGS':('MAILBOX',)})
    interaction_context=types.ModuleType('interactions.context')
    interaction_context.InteractionContext=FakeInteractionContext
    interaction_context.QueueInsertStrategy=types.SimpleNamespace(FIRST='FIRST')
    interactions=types.ModuleType('interactions'); interactions.__path__=[]
    interactions_priority=types.ModuleType('interactions.priority')
    interactions_priority.Priority=types.SimpleNamespace(High='HIGH')
    sys.modules['away_actions']=away_actions; sys.modules['away_actions.away_action_tracker']=away_action_tracker
    sys.modules['careers']=careers; sys.modules['careers.career_base']=career_base
    sys.modules['careers.career_location']=career_location; sys.modules['careers.career_ops']=career_ops
    sys.modules['date_and_time']=date_and_time
    sims_university=types.ModuleType('sims.university'); sims_university.__path__=[]
    world=types.ModuleType('world'); world.__path__=[]
    sys.modules['sims.university']=sims_university
    sys.modules['sims.university.university_career_tuning']=university_career
    sys.modules['world']=world; sys.modules['world.mailbox_owner_helper']=mailbox_helper
    sys.modules['interactions']=interactions; sys.modules['interactions.context']=interaction_context
    sys.modules['interactions.priority']=interactions_priority
    zone=types.ModuleType('zone')
    zone_types=types.ModuleType('zone_types')
    zone_types.ZoneState=types.SimpleNamespace(RUNNING='RUNNING')
    class FakeZone:
        def do_zone_spin_up(self, household_id, active_sim_id): return 'zone-result'
        def register_callback(self, state, callback): self.registered_callback=(state, callback)
    zone.Zone=FakeZone
    sys.modules['sims4']=sims4; sys.modules['sims4.log']=sims4.log
    sims=types.ModuleType('sims'); aging=types.ModuleType('sims.aging'); aging_mixin=types.ModuleType('sims.aging.aging_mixin'); aging_mixin.AgingMixin=FakeAgingMixin
    sim_info_types=types.ModuleType('sims.sim_info_types'); sim_info_types.Age=types.SimpleNamespace(TEEN=3,YOUNGADULT=4)
    university=types.ModuleType('sims.university'); enums=types.ModuleType('sims.university.university_enums')
    enums.EnrollmentStatus=types.SimpleNamespace(NONE=0,ENROLLED=1,NOT_ENROLLED=2,PROBATION=3)
    tuning=types.ModuleType('sims.university.university_tuning')
    tuning.University=types.SimpleNamespace(ALL_UNIVERSITIES=('Britechester','Foxbury'),ALL_DEGREES=('Biology','LanguageAndLiterature','FineArt','Drama','CulinaryArts','ComputerScience','Physics','Economics','Villainy','History','Communications'),choose_random_university=lambda:'Britechester',choose_random_major=lambda:'Biology')
    for name,module in {'services':services,'zone':zone,'zone_types':zone_types,'sims':sims,'sims.aging':aging,'sims.aging.aging_mixin':aging_mixin,'sims.sim_info_types':sim_info_types,'sims.university':university,'sims.university.university_enums':enums,'sims.university.university_tuning':tuning}.items(): sys.modules[name]=module
    path=pathlib.Path(__file__).parents[1]/'auto_university_enrollment.py'
    spec=importlib.util.spec_from_file_location('auto_university_enrollment_test',str(path)); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

class EnrollmentLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.mod=load_mod()
    def test_eligible_unplayed_npc(self): self.assertTrue(self.mod._eligible_for_enrollment(FakeSim()))
    def test_excludes_played_household(self): self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(played=True)))
    def test_excludes_selectable_sim(self): self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(selectable=True)))
    def test_excludes_previous_history(self): self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(tracker=FakeTracker(previous_majors=['prior']))))
    def test_excludes_completed_degree_from_public_history(self):
        class PublicHistoryTracker(FakeTracker):
            @property
            def previous_majors(self): return ('LanguageAndLiterature',)
        self.assertTrue(self.mod._has_completed_degree(PublicHistoryTracker()))
        self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(tracker=PublicHistoryTracker())))
    def test_enrollment_sequence(self):
        sim=FakeSim(); self.assertTrue(self.mod._enroll_sim(sim)); self.assertEqual(sim.degree_tracker.status,1)
        self.assertEqual(sim.degree_tracker.major,'Biology'); self.assertEqual(sim.degree_tracker.university,'Britechester')
        self.assertEqual(sim.degree_tracker.course_count,4)
        self.assertEqual(sim.degree_tracker.courses,[])
    def test_bestselling_author_prefers_language_and_literature(self):
        sim=FakeSim(aspiration='BestSellingAuthor')
        selected=self.mod._choose_major_for_aspiration(sim, self.mod.University.ALL_DEGREES)
        self.assertEqual(selected, 'LanguageAndLiterature')

    def test_unknown_aspiration_uses_random_major(self):
        sim=FakeSim(aspiration='UnknownAspiration')
        selected=self.mod._choose_major_for_aspiration(sim, self.mod.University.ALL_DEGREES)
        self.assertEqual(selected, 'Biology')

    def test_only_teen_to_young_adult_triggers(self):
        sim=FakeSim(); self.assertEqual(sim.change_age(4,3),'age-change-result'); self.assertEqual(sim.degree_tracker.status,1)
        other=FakeSim(); other.change_age(3,2); self.assertEqual(other.degree_tracker.status,0)

    def test_excludes_player_household(self):
        self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(player=True)))

    def test_excludes_missing_household(self):
        self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(household=False)))

    def test_excludes_existing_enrollment(self):
        tracker=FakeTracker(status=1)
        self.assertFalse(self.mod._eligible_for_enrollment(FakeSim(tracker=tracker)))

    def test_excludes_missing_degree_tracker(self):
        sim=FakeSim(); sim.degree_tracker=None
        self.assertFalse(self.mod._eligible_for_enrollment(sim))

    def test_rejects_empty_university_tuning(self):
        original=self.mod.University.ALL_UNIVERSITIES
        try:
            self.mod.University.ALL_UNIVERSITIES=()
            self.assertFalse(self.mod._enroll_sim(FakeSim()))
        finally:
            self.mod.University.ALL_UNIVERSITIES=original

    def test_startup_sweep_enrolls_existing_young_adults_once(self):
        existing=FakeSim(age=4)
        teen=FakeSim(age=3)
        manager=types.SimpleNamespace(get_all=lambda:[existing,teen])
        self.mod.services.sim_info_manager=lambda:manager
        self.mod._startup_sweep_completed=False
        self.mod._enroll_existing_young_adults()
        self.assertEqual(existing.degree_tracker.status,1)
        self.assertEqual(teen.degree_tracker.status,0)
        another=FakeSim(age=4)
        self.mod.services.sim_info_manager=lambda:types.SimpleNamespace(get_all=lambda:[another])
        self.mod._enroll_existing_young_adults()
        self.assertEqual(another.degree_tracker.status,0)

    def test_zone_spin_up_registers_sweep_for_running_state(self):
        zone=self.mod.Zone()
        self.assertEqual(zone.do_zone_spin_up(1,2),'zone-result')
        state, callback=zone.registered_callback
        self.assertEqual(state,'RUNNING')
        self.assertTrue(callable(callback))


    def _academic_career(self, class_day=10):
        sim=FakeSim()
        sim.degree_tracker.status=1
        sim.career_tracker.careers={1:FakeCourseCareer(class_day)}
        career=FakeCareerBase()
        career.sim_info=sim
        career._sim_info=sim
        career.is_course_slot=False
        career._at_work=False
        career.currently_at_work=False
        career._current_work_duration=FakeTimeSpan(8*60)
        return sim, career



    def test_unplayed_npc_university_student_automatically_takes_notes(self):
        sim=FakeSim()
        sim.degree_tracker.status=1
        career=FakeCareerBase()
        career.sim_info=sim
        career._sim_info=sim
        career.is_course_slot=True
        take_notes=FakeTone('UniversityTakeNotes')
        career.available_tones=(FakeTone('AttendClassNormally'),take_notes)
        career.start_tones()
        self.assertIs(sim.away_action_tracker.current_away_action,take_notes)
        self.assertTrue(sim.away_action_tracker.valid_during_apply)
        self.assertFalse(sim.away_action_tracker._aue_allow_university_take_notes)
        self.assertEqual(len(sim.away_action_tracker.started_callbacks),1)
        self.assertEqual(len(sim.away_action_tracker.ended_callbacks),1)

    def test_active_player_university_student_automatically_takes_notes(self):
        sim=FakeSim(npc=False,player=True)
        sim.degree_tracker.status=1
        career=FakeCareerBase()
        career.sim_info=sim
        career._sim_info=sim
        career.is_course_slot=True
        take_notes=FakeTone('UniversityTakeNotes')
        career.available_tones=(FakeTone('AttendClassNormally'),take_notes)
        career.start_tones()
        self.assertIs(sim.away_action_tracker.current_away_action,take_notes)
        self.assertTrue(sim.away_action_tracker.valid_during_apply)
        self.assertFalse(sim.away_action_tracker._aue_allow_university_take_notes)
        self.assertFalse(getattr(career,'original_start_tones_called',False))

    def test_unplayed_npc_non_university_career_keeps_vanilla_tone_behavior(self):
        sim=FakeSim()
        sim.degree_tracker.status=1
        career=FakeCareerBase()
        career.sim_info=sim
        career._sim_info=sim
        career.is_course_slot=False
        career.start_tones()
        self.assertTrue(career.original_start_tones_called)
        self.assertIsNone(sim.away_action_tracker.current_away_action)

    def test_missing_take_notes_tone_does_not_apply_another_action(self):
        sim=FakeSim()
        sim.degree_tracker.status=1
        career=FakeCareerBase()
        career.sim_info=sim
        career._sim_info=sim
        career.is_course_slot=True
        career.available_tones=(FakeTone('AttendClassNormally'),)
        career.start_tones()
        self.assertIsNone(sim.away_action_tracker.current_away_action)

    def test_future_shift_day_is_used_for_class_match(self):
        sim,career=self._academic_career(class_day=11)
        reason=career._get_drama_node_time_off_reason(FakeDateTime(11))
        self.assertEqual(reason,'FAKE_SICK')
        self.assertTrue(career._aue_academic_day_off)

    def test_standard_npc_dispatch_is_suppressed_for_academic_leave(self):
        sim,career=self._academic_career()
        career._aue_academic_day_off=True
        location=FakeCareerLocation()
        location._career=career
        self.assertIsNone(location.on_npc_start_work())
        self.assertFalse(getattr(location,'original_npc_start_called',False))

    def test_service_npc_dispatch_is_suppressed_for_academic_leave(self):
        sim,career=self._academic_career()
        career._aue_academic_day_off=True
        location=FakeCareerLocationServiceNpc()
        location._career=career
        self.assertIsNone(location.on_npc_start_work())
        self.assertFalse(getattr(location,'original_npc_start_called',False))

    def test_npc_dispatch_continues_without_academic_leave(self):
        sim,career=self._academic_career()
        location=FakeCareerLocation()
        location._career=career
        self.assertEqual(location.on_npc_start_work(),'npc-start-result')
        self.assertTrue(location.original_npc_start_called)

    def test_native_drama_query_grants_academic_leave(self):
        sim,career=self._academic_career()
        reason=career._get_drama_node_time_off_reason()
        self.assertEqual(reason,'FAKE_SICK')
        self.assertTrue(career._aue_academic_day_off)

    def test_class_is_compared_to_future_work_shift_day(self):
        sim,career=self._academic_career(class_day=11)
        reason=career._get_drama_node_time_off_reason(FakeDateTime(11))
        self.assertEqual(reason,'FAKE_SICK')
        self.assertTrue(career._aue_academic_day_off)

    def test_native_early_warning_receives_academic_reason(self):
        sim,career=self._academic_career()
        self.assertEqual(career.early_warning_callback(),'early-warning-result')
        self.assertTrue(career.original_early_warning_called)
        self.assertEqual(career.requested_day_off_reason,'FAKE_SICK')
        self.assertTrue(career._aue_academic_day_off)

    def test_native_holiday_reason_takes_precedence(self):
        sim,career=self._academic_career()
        original=self.mod._original_get_drama_node_time_off_reason
        try:
            self.mod._original_get_drama_node_time_off_reason=lambda self,end_time=None:'HOLIDAY_REASON'
            self.assertEqual(career._get_drama_node_time_off_reason(),'HOLIDAY_REASON')
            self.assertFalse(getattr(career,'_aue_academic_day_off',False))
        finally:
            self.mod._original_get_drama_node_time_off_reason=original

    def test_non_class_day_does_not_grant_leave(self):
        sim,career=self._academic_career(class_day=11)
        self.assertEqual(career._get_drama_node_time_off_reason(),'NO_TIME_OFF')
        self.assertFalse(getattr(career,'_aue_academic_day_off',False))

    def test_active_player_sim_receives_academic_leave(self):
        sim,career=self._academic_career()
        sim.is_npc=False
        sim.is_player_sim=True
        sim.is_played_sim=True
        sim.is_selectable=True
        sim.household.is_player_household=True
        sim.household.is_played_household=True
        self.assertEqual(career._get_drama_node_time_off_reason(),'FAKE_SICK')
        self.assertTrue(career._aue_academic_day_off)

    def test_active_player_sim_attend_work_is_suppressed_and_paid_once(self):
        sim,career=self._academic_career()
        sim.is_npc=False
        sim.is_player_sim=True
        sim.is_played_sim=True
        sim.is_selectable=True
        sim.household.is_player_household=True
        sim.household.is_played_household=True
        self.assertIsNone(career.attend_work())
        self.assertFalse(getattr(career,'original_attend_work_called',False))
        self.assertFalse(hasattr(career,'paid_hours'))
        self.assertTrue(career._aue_academic_day_off)
        self.assertFalse(getattr(career,'_aue_academic_day_off_paid',False))
        self.assertIsNone(career.attend_work())
        self.assertFalse(hasattr(career,'paid_hours'))

    def test_unenrolled_sim_does_not_receive_academic_leave(self):
        sim,career=self._academic_career()
        sim.degree_tracker.status=0
        self.assertEqual(career._get_drama_node_time_off_reason(),'NO_TIME_OFF')
        self.assertFalse(getattr(career,'_aue_academic_day_off',False))

    def test_attend_work_final_guard_suppresses_npc_and_pays_once(self):
        sim,career=self._academic_career()
        self.assertIsNone(career.attend_work())
        self.assertFalse(getattr(career,'original_attend_work_called',False))
        self.assertEqual(career.paid_hours,8.0)
        self.assertTrue(career._aue_academic_day_off)
        self.assertTrue(career._aue_academic_day_off_paid)
        # A duplicate invocation must not issue a second payment.
        self.assertIsNone(career.attend_work())
        self.assertEqual(career.paid_hours,8.0)

    def test_attend_work_continues_on_non_class_day(self):
        sim,career=self._academic_career(class_day=11)
        self.assertEqual(career.attend_work(),'attend-work-result')
        self.assertTrue(career.original_attend_work_called)
        self.assertFalse(getattr(career,'_aue_academic_day_off',False))

    def test_attend_work_blocks_played_sim_on_class_day(self):
        sim,career=self._academic_career()
        sim.is_npc=False
        sim.is_player_sim=True
        sim.is_played_sim=True
        sim.is_selectable=True
        sim.household.is_player_household=True
        sim.household.is_played_household=True
        self.assertIsNone(career.attend_work())
        self.assertFalse(getattr(career,'original_attend_work_called',False))
        self.assertTrue(career._aue_academic_day_off)
        self.assertFalse(hasattr(career,'paid_hours'))

    def test_npc_academic_leave_receives_full_shift_pay(self):
        sim,career=self._academic_career()
        self.assertEqual(career._get_drama_node_time_off_reason(),'FAKE_SICK')
        self.assertEqual(career._end_work_callback(None),'career-end-result')
        self.assertEqual(career.paid_hours,8.0)
        self.assertTrue(career.original_end_called)
        self.assertFalse(career._aue_academic_day_off)

    def test_no_manual_pay_without_academic_marker(self):
        sim,career=self._academic_career()
        self.assertEqual(career._end_work_callback(None),'career-end-result')
        self.assertFalse(hasattr(career,'paid_hours'))


    def _home_course_slot(self):
        sim=FakeSim(npc=False,player=True)
        sim.degree_tracker.status=1
        sim_instance=FakeSimInstance()
        slot=FakeUniversityCourseCareerSlot()
        slot.sim_info=sim
        slot._sim_info=sim
        slot.sim_instance=sim_instance
        slot.work_early_affordance=FakeTone('GoToClassEarly')
        slot.guid64=123
        slot.career_messages=types.SimpleNamespace(career_early_warning_time=1)
        slot.get_next_work_time=lambda: (FakeTimeSpan(30),FakeDateTime(10),None)
        return sim,slot,sim_instance

    def test_home_class_early_warning_is_available_one_hour_before(self):
        sim,slot,sim_instance=self._home_course_slot()
        self.assertTrue(self.mod._can_wait_for_class_at_home(slot))
        self.assertTrue(slot.can_work_early())

    def test_home_early_class_routes_to_mailbox_first_in_queue(self):
        sim,slot,sim_instance=self._home_course_slot()
        self.assertIsNotNone(self.mod._get_home_mailbox(sim))
        self.assertIs(slot._get_sim(),sim_instance)
        slot.go_to_work_early()
        self.assertEqual(len(sim_instance.pushed),1)
        args,kwargs=sim_instance.pushed[0]
        self.assertIs(args[0],slot.work_early_affordance)
        self.assertIsInstance(args[1],FakeMailbox)
        self.assertEqual(args[2].kwargs['insert_strategy'],'FIRST')
        self.assertEqual(kwargs['career_uid'],123)

    def test_home_preparation_not_available_without_enrollment(self):
        sim,slot,sim_instance=self._home_course_slot()
        sim.degree_tracker.status=0
        self.assertFalse(self.mod._can_wait_for_class_at_home(slot))

    def test_home_preparation_not_available_without_mailbox(self):
        sim,slot,sim_instance=self._home_course_slot()
        original=self.mod.services.object_manager
        self.mod.services.object_manager=lambda: types.SimpleNamespace(get_objects_with_tags_gen=lambda *tags: iter(()))
        try:
            self.assertFalse(self.mod._can_wait_for_class_at_home(slot))
        finally:
            self.mod.services.object_manager=original

    def test_home_preparation_not_available_outside_home_zone(self):
        sim,slot,sim_instance=self._home_course_slot()
        original=self.mod.services.current_zone_id
        self.mod.services.current_zone_id=lambda: 99
        try:
            self.assertIsNone(self.mod._get_home_mailbox(sim))
            self.assertFalse(self.mod._can_wait_for_class_at_home(slot))
        finally:
            self.mod.services.current_zone_id=original


if __name__=='__main__': unittest.main()

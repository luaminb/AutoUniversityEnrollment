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
        self.major=major; self.university=university; self.status=1

class FakeAgingMixin:
    def change_age(self,new_age,current_age): self.last_age_change=(new_age,current_age); return 'age-change-result'

class FakeSim(FakeAgingMixin):
    def __init__(self, npc=True, player=False, played=False, selectable=False, tracker=None, household=True, age=4):
        self.is_npc=npc; self.is_player_sim=player; self.is_played_sim=played; self.is_selectable=selectable; self.age=age
        self.household=types.SimpleNamespace(is_player_household=player,is_played_household=played) if household else None
        self.degree_tracker=tracker or FakeTracker()

def load_mod():
    sims4=types.ModuleType('sims4'); sims4.log=types.SimpleNamespace(Logger=FakeLogger)
    services=types.ModuleType('services'); services.sim_info_manager=lambda: None
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
    tuning.University=types.SimpleNamespace(ALL_UNIVERSITIES=('Britechester','Foxbury'),ALL_DEGREES=('Biology','Arts'),choose_random_university=lambda:'Britechester',choose_random_major=lambda:'Biology')
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
    def test_enrollment_sequence(self):
        sim=FakeSim(); self.assertTrue(self.mod._enroll_sim(sim)); self.assertEqual(sim.degree_tracker.status,1)
        self.assertEqual(sim.degree_tracker.major,'Biology'); self.assertEqual(sim.degree_tracker.university,'Britechester')
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

if __name__=='__main__': unittest.main()

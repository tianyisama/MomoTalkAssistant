from momotalk_assistant.models import Action, Box, Observation, Scene, Target
from momotalk_assistant.planner import Planner
from momotalk_assistant.runner import StabilityGate


def observation(scene=Scene.MOMO, tab="chat", sort="unread", keys=(), **meta):
    obs=Observation(scene=scene,meta={"tab":tab,"sort":sort,**meta})
    for key in keys: obs.add(key,Box(100,100,80,30),.95)
    return obs


def run_refresh(planner, now=1):
    unread=observation(keys=("people_tab","chat_tab","first_unread"),nav_unread=True)
    action=planner.propose(unread,now)
    assert action and action.key=="people_tab"
    planner.committed(action,unread,now)
    people=observation(tab="people",sort=None,keys=("people_tab","chat_tab"))
    action=planner.propose(people,now+1)
    assert action and action.key=="chat_tab"
    planner.committed(action,people,now+1)
    assert planner.propose(unread,now+2) is None
    assert planner.propose(unread,now+4) is None
    assert planner.filter_verified
    return unread


def test_latest_never_selects_a_row_even_if_reply_and_row_are_visible():
    p=Planner()
    obs=observation(sort="latest",keys=("sort_button","first_unread","reply_first"))
    assert p.propose(obs,0).key=="sort_button"
    assert not p.filter_verified


def test_unread_selection_requires_selected_color_and_ok_then_refresh():
    p=Planner()
    before=observation(Scene.SORT,keys=("sort_unread","sort_ok"),unread_selected=False)
    action=p.propose(before,1)
    assert action.key=="sort_unread"
    p.committed(action,before,1)
    assert p.propose(before,2).key=="sort_unread"  # no assumed success
    selected=observation(Scene.SORT,keys=("sort_unread","sort_ok"),unread_selected=True)
    assert p.propose(selected,3).key=="sort_ok"
    unread=run_refresh(p,4)
    assert p.propose(unread,9).key=="first_unread"


def test_failed_people_tab_does_not_advance_refresh():
    p=Planner()
    obs=observation(keys=("people_tab","chat_tab","first_unread"))
    action=p.propose(obs,0); p.committed(action,obs,0)
    assert p.propose(obs,2).key=="people_tab"
    assert not p.filter_verified


def test_typing_pause_never_becomes_done_or_clicks_another_row():
    p=Planner(idle_seconds=35)
    obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    for now in [7,9,12,16,25,35]:
        assert p.propose(obs,now) is None
        assert p.in_chat


def test_story_cycle_confirmed_from_screens_then_refreshes():
    p=Planner(); obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    for now,scene,key in [(8,Scene.MOMO,"reply_first"),(11,Scene.MOMO,"bond_enter"),
                           (13,Scene.STORY_INFO,"story_start"),(16,Scene.STORY,"story_menu"),
                           (18,Scene.STORY_MENU,"fast_forward"),(20,Scene.SKIP_CONFIRM,"skip_ok"),
                           (24,Scene.REWARD,"reward_touch")]:
        current=observation(scene,keys=(key,))
        action=p.propose(current,now)
        assert action and action.key==key
        p.committed(action,current,now)
    assert p.stats.stories==0  # a successful input alone is not a reward confirmation
    assert p.propose(obs,26).key=="people_tab"
    assert p.stats.stories==1


def test_chat_badge_disappearance_closes_momo_then_checks_home():
    p=Planner(); run_refresh(p)
    empty=observation(keys=("people_tab","chat_tab","momo_close"),nav_unread=False)
    assert p.propose(empty,8) is None
    action=p.propose(empty,9.1)
    assert action.key=="momo_close" and action.kind=="tap"
    p.committed(action,empty,9.1)
    home=observation(Scene.HOME,keys=("open_momo",),home_unread=False)
    assert p.propose(home,10) is None
    assert p.propose(home,11.2).kind=="done"


def test_home_badge_still_present_reopens_momo_instead_of_stopping():
    p=Planner(); p.checking_home=True; p.filter_verified=True
    home=observation(Scene.HOME,keys=("open_momo",),home_unread=True)
    action=p.propose(home,5)
    assert action.key=="open_momo" and action.kind=="tap"
    assert not p.filter_verified and not p.checking_home


def test_home_absence_needs_consecutive_observations():
    p=Planner()
    home=observation(Scene.HOME,keys=("open_momo",),home_unread=False)
    assert p.propose(home,0) is None
    assert p.propose(observation(Scene.UNKNOWN),10) is None
    assert p.propose(home,12) is None
    assert p.propose(home,13.2).kind=="done"


def test_missing_home_badge_evidence_never_means_complete():
    p=Planner()
    home=observation(Scene.HOME,keys=("open_momo",))
    assert p.propose(home,0) is None
    assert p.propose(home,30) is None


def test_active_reply_is_processed_before_a_home_completion_check():
    p=Planner(); obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    reply=observation(keys=("reply_first","momo_close"),nav_unread=False)
    assert p.propose(reply,8).key=="reply_first"


def test_chat_badge_disappearance_does_not_wait_for_idle_timeout():
    p=Planner(idle_seconds=120); obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    no_badge=observation(keys=("momo_close",),nav_unread=False)
    assert p.propose(no_badge,7) is None
    assert p.propose(no_badge,8.2).key=="momo_close"


def test_wait_setting_changes_an_existing_conversation_immediately():
    from momotalk_assistant.options import RunOptions
    options=RunOptions(35)
    p=Planner(options=options); obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    assert p.propose(obs,12) is None
    options.set_idle_seconds(3)
    assert p.propose(obs,12.1).key=="people_tab"


def test_wait_setting_can_be_increased_without_restarting():
    from momotalk_assistant.options import RunOptions
    options=RunOptions(8)
    p=Planner(options=options); obs=run_refresh(p)
    action=p.propose(obs,6); p.committed(action,obs,6)
    options.set_idle_seconds(30)
    assert p.propose(obs,25) is None
    assert p.propose(obs,37).key=="people_tab"


def test_visible_unread_badge_prevents_done():
    p=Planner(); run_refresh(p)
    marked=observation(nav_unread=True)
    assert p.propose(marked,10) is None
    assert p.propose(marked,20) is None


def test_stability_gate_requires_same_target_in_two_consecutive_frames():
    gate=StabilityGate()
    a=Action("reply_first","reply",Target("reply_first",Box(100,100,200,40)))
    elsewhere=Action("reply_first","reply",Target("reply_first",Box(100,300,200,40)))
    assert not gate.accept(a)
    assert not gate.accept(elsewhere)
    assert gate.accept(elsewhere)
    assert not gate.accept(None)
    assert not gate.accept(elsewhere)

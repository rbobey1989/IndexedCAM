from IndexedCAM.Core.preview import OPERATION, TRANSITION, Clip, PreviewFrame
from IndexedCAM.Core.program import ChainedStep, Step
from IndexedCAM.Core.simulation_plan import SimulationPlan, TiltScript, plan_from_clips
from IndexedCAM.Machine.bc_machine import BCMachine


def _clip(kind, index, frames):
    envelope = BCMachine().envelope
    return Clip(kind, "t", index, frames, envelope, lambda tip, b, c: None)


def _items():
    return [
        ChainedStep(Step("A", "Op1"), None, None, None, False),
        ChainedStep(Step("B", "Op2"), None, None, None, True),
    ]


def _plan():
    f = lambda b, c: PreviewFrame((0.0, 0.0, 0.0), b, c)
    clips = [
        _clip(OPERATION, 0, [f(0, 0)]),
        _clip(TRANSITION, 1, [f(10, 0), f(20, 5)]),
        _clip(OPERATION, 1, [f(30, 90), f(30, 90)]),
    ]
    return plan_from_clips(_items(), clips)


def test_plan_maps_operations_and_transitions():
    plan = _plan()
    assert plan.orientation("Op2") == (30, 90)
    assert plan.orientation("Op1") == (0, 0)
    assert len(plan.transition("Op2")) == 2
    assert plan.transition("Op1") == []
    assert plan.orientation("Other") is None


def test_script_plays_transition_once_per_operation():
    script = TiltScript(_plan())
    script.enter("Op2")
    assert script.next_transition_frame().b == 10
    script.enter("Op2")
    assert script.next_transition_frame().b == 20
    assert script.next_transition_frame() is None


def test_script_reset_replays():
    script = TiltScript(_plan())
    script.enter("Op2")
    script.reset()
    script.enter("Op2")
    assert len(script._queue) == 2


def test_script_pending_and_skip():
    script = TiltScript(_plan())
    assert not script.pending()
    script.enter("Op2")
    assert script.pending()
    script.skip()
    assert not script.pending()

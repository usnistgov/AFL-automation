import json

import pytest

from AFL.automation.double_agent.AgentDriver import DoubleAgentDriver


@pytest.fixture
def driver():
    return DoubleAgentDriver(overrides={"mock_mode": True})


def test_defaults_and_status(driver):
    status = driver.status()
    assert any("mock_mode" in s for s in status)
    assert "save_path" in driver.defaults


def test_initialize_pipeline_sets_config(driver):
    ops = [{"class": "TestOp", "args": {"input_variable": "x", "output_variable": "y"}}]
    res = driver.initialize_pipeline(pipeline=ops, name="TestPipe")
    assert res["status"] == "success"
    current = driver.current_pipeline()
    assert current is not None
    assert current["ops"]
    assert isinstance(current["connections"], list)


def test_assemble_input_in_mock_mode(driver):
    out = driver.assemble_input_from_tiled()
    assert out["status"] == "success"
    assert driver.input is not None


def test_predict_in_mock_mode(driver):
    driver.initialize_pipeline(pipeline=[{"class": "TestOp"}])
    driver.assemble_input_from_tiled()
    result = driver.predict()
    assert "pipeline_ops" in result
    assert driver.last_results == result


def test_build_and_analyze_pipeline(driver):
    ops_json = json.dumps([
        {"class": "OpA", "args": {"output_variable": "a"}},
        {"class": "OpB", "args": {"input_variable": "a", "output_variable": "b"}},
    ])
    built = driver.build_pipeline(ops=ops_json)
    assert built["connections"]
    analysis = driver.analyze_pipeline(ops=ops_json)
    assert analysis["status"] == "success"
    assert analysis["connections"]

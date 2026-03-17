from AFL.automation.prepare.OT2Prepare import OT2Prepare


class StubOT2Prepare(OT2Prepare):
    def __init__(self):
        self.app = None
        self.data = {"prepare": {"executed_transfers": []}}
        self.config = {
            "deck": {"1A1": "Water"},
            "stock_transfer_params": {
                "default": {"drop_tip": True},
                "Water": {"mix_after": [1, 10]},
            },
        }
        self.stocks = []
        self.last_target_location = None

    def transfer(self, source, dest, volume, **kwargs):
        return {
            "source": source,
            "dest": dest,
            "requested_volume_ul": float(volume),
            "subtransfers_ul": [float(volume)],
            "pipette_mount": "left",
            "pipette_name": "p300_single",
        }


def test_transfer_stage_records_prepare_execution_metadata():
    driver = StubOT2Prepare()

    driver._transfer_stage(
        source="1A1",
        dest="5A1",
        volume_ul=50.0,
        stage_type="single",
        source_stock_name="Water",
        planned_transfer={"required_volume_ul": 50.0},
        extra={"destination_location": "5A1"},
    )

    executed = driver.data["prepare"]["executed_transfers"]
    assert len(executed) == 1
    entry = executed[0]
    assert entry["stage_type"] == "single"
    assert entry["source_location"] == "1A1"
    assert entry["dest_location"] == "5A1"
    assert entry["source_stock_name"] == "Water"
    assert entry["requested_volume_ul"] == 50.0
    assert entry["transfer_params"]["mix_after"] == [1, 10]
    assert entry["transfer_result"]["subtransfers_ul"] == [50.0]
    assert entry["planned_transfer"]["required_volume_ul"] == 50.0

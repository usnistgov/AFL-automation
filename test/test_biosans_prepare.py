from AFL.automation.mixing import MixDB as mixdb_module
from AFL.automation.mixing.BioSANSPrepare import BioSANSPrepare


def test_biosans_prepare_initializes_mixdb_singleton(monkeypatch):
    monkeypatch.setattr(mixdb_module, "_MIXDB", None)

    driver = BioSANSPrepare()
    driver.config.write = False

    assert hasattr(driver, "mixdb")
    assert driver.mixdb is mixdb_module.MixDB.get_db()

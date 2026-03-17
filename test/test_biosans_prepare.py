from AFL.automation.mixcalc.MixDB import MixDB
from AFL.automation.prepare.BioSANSPrepare import BioSANSPrepare


def test_biosans_prepare_initializes_mixdb_singleton():
    driver = BioSANSPrepare()
    driver.config.write = False

    assert hasattr(driver, "mixdb")
    assert driver.mixdb is MixDB.get_db()

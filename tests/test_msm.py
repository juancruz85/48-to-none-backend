import unittest

from src import msm


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.operationalstate = False
        msm.errorstate = False
        msm.errordetected = False
        msm.last_error = None

    def test_startup(self):
        msm.start()
        self.assertEqual(msm.state, msm.State.STARTING)

        msm.startup_succeeded()
        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertTrue(msm.operationalstate)
        self.assertFalse(msm.errorstate)

    def test_error_and_recovery(self):
        msm.start()
        msm.startup_succeeded()

        msm.enter_error("example failure")
        self.assertEqual(msm.state, msm.State.ERROR)
        self.assertEqual(msm.last_error, "example failure")
        self.assertTrue(msm.errorstate)
        self.assertTrue(msm.errordetected)

        msm.begin_recovery()
        self.assertEqual(msm.state, msm.State.RECOVERING)
        msm.recovery_succeeded()
        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertIsNone(msm.last_error)

    def test_rejects_invalid_transition(self):
        with self.assertRaises(ValueError):
            msm.startup_succeeded()

    def test_shutdown(self):
        msm.start()
        msm.startup_succeeded()
        msm.shutdown()
        self.assertEqual(msm.state, msm.State.STOPPED)
        self.assertFalse(msm.operationalstate)
        self.assertFalse(msm.errorstate)

    def test_failed_recovery_returns_to_error(self):
        msm.start()
        msm.startup_succeeded()
        msm.enter_error("initial failure")
        msm.begin_recovery()

        msm.recovery_failed("repair failed")
        self.assertEqual(msm.state, msm.State.ERROR)
        self.assertEqual(msm.last_error, "repair failed")
        self.assertTrue(msm.errorstate)


if __name__ == "__main__":
    unittest.main()

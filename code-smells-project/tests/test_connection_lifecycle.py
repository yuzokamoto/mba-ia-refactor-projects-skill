import unittest
from unittest.mock import Mock, call

from models.connection import ConnectionLifecycle


class ConnectionLifecycleTests(unittest.TestCase):
    def test_rollback_failure_closes_connection_and_allows_recovery(self):
        state = {}
        failed, replacement = Mock(), Mock()
        failed.rollback.side_effect = RuntimeError("Falha simulada")
        database = Mock()
        database.connect.side_effect = [failed, replacement]
        lifecycle = ConnectionLifecycle(database, lambda: state)

        self.assertIs(lifecycle.acquire(), failed)
        self.assertIs(lifecycle.acquire(), failed)
        database.connect.assert_called_once_with()
        with self.assertRaisesRegex(RuntimeError, "Falha simulada"):
            lifecycle.release()
        self.assertEqual(failed.method_calls, [call.rollback(), call.close()])
        self.assertEqual(state, {})

        lifecycle.release()
        self.assertEqual(database.connect.call_count, 1)
        self.assertIs(lifecycle.acquire(), replacement)
        lifecycle.release()
        self.assertEqual(replacement.method_calls, [call.rollback(), call.close()])


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import main


class JobRunnerEndpointTests(unittest.TestCase):
    def test_run_jobs_processes_batch_with_valid_token(self):
        with patch.object(main, "JOB_RUNNER_TOKEN", "secret"), patch.object(
            main,
            "JOB_RUNNER_BATCH_SIZE",
            7,
        ), patch.object(main, "run_due_jobs", return_value=4) as run_due_jobs:
            result = main.run_jobs(x_job_token="secret")

        self.assertEqual(result, {"status": "ok", "processed": 4})
        run_due_jobs.assert_called_once_with(7)

    def test_run_jobs_rejects_wrong_token(self):
        with patch.object(main, "JOB_RUNNER_TOKEN", "secret"):
            with self.assertRaises(HTTPException) as ctx:
                main.run_jobs(x_job_token="wrong")

        self.assertEqual(ctx.exception.status_code, 403)

    def test_run_jobs_requires_token_in_production(self):
        with patch.object(main, "JOB_RUNNER_TOKEN", None), patch.object(main, "ENV", "production"):
            with self.assertRaises(HTTPException) as ctx:
                main.run_jobs(x_job_token=None)

        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()

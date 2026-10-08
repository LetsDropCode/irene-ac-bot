// Railway cron function: call the authenticated runner and exit after each run.
const url = process.env.JOB_RUNNER_URL;
const token = process.env.JOB_RUNNER_TOKEN;

if (!url || !token) {
  throw new Error("JOB_RUNNER_URL and JOB_RUNNER_TOKEN are required");
}

const response = await fetch(url, {
  method: "POST",
  headers: { "x-job-token": token },
  signal: AbortSignal.timeout(60_000),
});

if (!response.ok) {
  throw new Error(`Job runner returned HTTP ${response.status}`);
}

const result = await response.json() as {
  status: string;
  processed: number;
  reminder_candidates: number;
};

console.log(JSON.stringify({
  status: result.status,
  processed: result.processed,
  reminder_candidates: result.reminder_candidates,
}));

const app = {
  cwd: "/var/www/fleet",
  interpreter: "none",
  uid: "fleet",
  gid: "fleet",
  env: { FLEET_ENV: "/etc/fleet.env" },
};

module.exports = {
  apps: [
    {
      ...app,
      name: "fleet-api",
      script: ".venv/bin/uvicorn",
      args: "app.api:app --host 127.0.0.1 --port 3008 --workers 1 --proxy-headers",
      max_memory_restart: "350M",
    },
    {
      ...app,
      name: "fleet-worker",
      script: ".venv/bin/python",
      args: "-m app.worker",
      max_memory_restart: "300M",
    },
    {
      // Reads execution logs of the shared n8n; runs as root because that database is not ours.
      name: "fleet-n8n-reader",
      cwd: "/var/www/fleet",
      script: "scripts/n8n-reader.mjs",
      node_args: "--disable-warning=ExperimentalWarning",
      max_memory_restart: "100M",
    },
  ],
};

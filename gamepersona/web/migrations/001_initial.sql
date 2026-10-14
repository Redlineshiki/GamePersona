CREATE TABLE users (
 id text PRIMARY KEY, steam_id text UNIQUE NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), deleting boolean NOT NULL DEFAULT false
);
CREATE TABLE sessions (
 token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf text NOT NULL, expires_at timestamptz NOT NULL
);
CREATE INDEX sessions_owner ON sessions(user_id);
CREATE TABLE login_transactions (
 state_hash text PRIMARY KEY, binding_hash text NOT NULL,
 user_id text REFERENCES users(id) ON DELETE CASCADE,
 return_to text NOT NULL, expires_at timestamptz NOT NULL, consumed boolean NOT NULL DEFAULT false
);
CREATE TABLE openid_nonces (nonce_hash text PRIMARY KEY, expires_at timestamptz NOT NULL);
CREATE TABLE tasks (
 id text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 state text NOT NULL CHECK(state IN ('pending','running','succeeded','failed')),
 reference_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 read_status text, report_id text, error_code text
);
CREATE UNIQUE INDEX one_active_task ON tasks(user_id) WHERE state IN ('pending','running');
CREATE TABLE input_snapshots (
 id text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 task_id text NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 read_status text NOT NULL, records jsonb NOT NULL, content_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE reports (
 id text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 task_id text REFERENCES tasks(id) ON DELETE CASCADE,
 input_id text REFERENCES input_snapshots(id) ON DELETE CASCADE,
 payload jsonb NOT NULL, report_sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reports_owner ON reports(user_id,created_at DESC);

import { Pool } from "pg";

// Singleton pool, dev-hot-reload-safe. Next's Turbopack dev server
// re-evaluates modules on every fast refresh - without stashing the pool on
// `global`, each refresh would open a fresh Pool (its own connection set)
// against the same production Supabase database backend/mastery already
// depends on, a realistic way to exhaust its connection limit during a dev
// session. Same shape as the standard Prisma-client-singleton workaround for
// the identical problem.
//
// This reads process.env.DATABASE_URL directly via Next's own env loading -
// no dotenv call here at all, so the exact footgun already found and fixed
// this session in backend/mastery/db.py and backend/voice/bot.py
// (load_dotenv(override=True) letting .env silently win over the shell's own
// environment) has no way to recur in this file.
declare global {
  // eslint-disable-next-line no-var
  var _pgPool: Pool | undefined;
}

export const pool =
  global._pgPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false },
  });

if (process.env.NODE_ENV !== "production") {
  global._pgPool = pool;
}

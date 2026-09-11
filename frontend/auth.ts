import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { pool } from "@/lib/db";

// One login = one parent account = access to exactly one student profile
// (hackathon scope, matches the app's existing single-student-everywhere
// architecture - see db/schema.sql). JWT session strategy, no database
// adapter: app_users is only ever queried inside authorize() below, nothing
// else in next-auth's own machinery touches Postgres.
export const { handlers, signIn, signOut, auth } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: {},
        password: {},
      },
      authorize: async (credentials) => {
        const email = (credentials?.email as string | undefined)?.toLowerCase().trim();
        const password = credentials?.password as string | undefined;
        if (!email || !password) return null;

        const { rows } = await pool.query(
          "select id, email, password_hash, student_id, display_name, grade from app_users where email = $1",
          [email]
        );
        const row = rows[0];
        if (!row) return null;

        const valid = await bcrypt.compare(password, row.password_hash);
        if (!valid) return null;

        return {
          id: row.id,
          email: row.email,
          studentId: row.student_id,
          displayName: row.display_name,
          grade: row.grade,
        };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.studentId = user.studentId;
        token.displayName = user.displayName;
        token.grade = user.grade;
      }
      return token;
    },
    session({ session, token }) {
      session.user.studentId = token.studentId as string;
      session.user.displayName = token.displayName as string;
      session.user.grade = token.grade as number;
      return session;
    },
  },
});

import { DefaultSession } from "next-auth";

// Module augmentation: adds the real per-login student identity (created at
// signup via the existing createStudent() flow, lib/api.ts) onto every
// place next-auth's own types normally only carry name/email/image.
declare module "next-auth" {
  interface Session {
    user: {
      studentId: string;
      displayName: string;
      grade: number;
    } & DefaultSession["user"];
  }

  interface User {
    studentId: string;
    displayName: string;
    grade: number;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    studentId: string;
    displayName: string;
    grade: number;
  }
}

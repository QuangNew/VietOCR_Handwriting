"use client";
import dynamic from "next/dynamic";

// A production build must not include the annotation runtime or contact an MCP server.
const Feedback = process.env.NODE_ENV === "development"
  ? dynamic(() => import("agentation").then(m => m.Agentation), { ssr: false }) : null;
export function DevFeedback() {
  return Feedback ? <Feedback /> : null;
}

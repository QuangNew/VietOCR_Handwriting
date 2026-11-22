import type { Metadata } from "next";
import { DevFeedback } from "@/components/dev-feedback";
import "./globals.css";

export const metadata: Metadata = { title: "VietHandOCR Control", description: "Không gian vận hành VietHandOCR trên máy của bạn." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body>{children}<DevFeedback /></body></html>;
}

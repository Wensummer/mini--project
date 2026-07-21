import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "登记智鉴｜企业登记合规监测",
  description: "统一标准、监测预警、证据核验与整改闭环一体化平台。",
  openGraph: {
    title: "登记智鉴｜企业登记合规监测",
    description: "从统一标准到监测预警、证据核验和整改闭环。",
    images: [{ url: "/og-roadshow.png", width: 1200, height: 630 }],
    locale: "zh_CN",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "登记智鉴",
    description: "企业登记注册合规风险监测",
    images: ["/og-roadshow.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

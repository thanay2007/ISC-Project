import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Shell } from "@/components/shell";
import { AnalyzerPage } from "@/components/analyzer";
import { DashboardPage, HistoryPage, IssuePage, VerifyPage } from "@/components/operations";
import { AssistantPage, ReportsPage } from "@/components/reports-assistant";
import { DemoPage, InstitutionsPage, SecurityPage } from "@/components/admin-demo";
import { ModelPage, SettingsPage } from "@/components/model-settings";
import { Loading } from "@/components/ui";

const pages = {
  dashboard: DashboardPage, analyzer: AnalyzerPage, compare: () => <AnalyzerPage comparison />, assistant: AssistantPage,
  history: HistoryPage, reports: ReportsPage, issue: IssuePage, security: SecurityPage, demo: DemoPage,
  institutions: InstitutionsPage, admin: () => <InstitutionsPage admin />, "model-performance": ModelPage, settings: SettingsPage,
};

export default async function Workspace({ params }: { params: Promise<{ route: string[] }> }) {
  const { route: [name, reference, extra] } = await params;
  if (name === "verify" && !extra && (!reference || /^[a-f0-9]{32}$/i.test(reference))) {
    return <Shell publicPage><VerifyPage reference={reference?.toLowerCase()} /></Shell>;
  }
  if (reference || !Object.hasOwn(pages, name)) notFound();
  const Page = pages[name as keyof typeof pages];
  return <Shell publicPage={name === "model-performance"}><Suspense fallback={<Loading />}><Page /></Suspense></Shell>;
}

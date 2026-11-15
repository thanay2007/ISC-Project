import Link from "next/link";
import { ArrowRight, Binary, BrainCircuit, FileCheck2, Fingerprint, LogIn, ScanLine, ShieldCheck } from "lucide-react";
import { Brand } from "@/components/ui";
import { Button } from "@/components/ui/button";

export default function Landing() {
  return <div className="landing">
    <header className="landing-nav"><Brand /><Button asChild className="landing-sign-in"><Link href="/login"><LogIn size={17} /> Sign in</Link></Button></header>
    <main>
      <section className="landing-hero">
        <div className="hero-copy"><h1>Trust every document.<br /><em>Verify every detail.</em></h1>
          <p>Check bills, invoices, certificates, and other documents for signs of editing. Review the evidence and download a forensic report.</p>
          <div className="hero-actions"><Button asChild><Link href="/login?next=%2Fanalyzer">Analyze a document <ArrowRight size={17} /></Link></Button></div>
        </div>
        <div className="hero-visual" aria-hidden="true"><div className="visual-rings" /><div className="visual-grid" /><div className="visual-tag"><span /> EVIDENCE WORKBENCH</div>
          <div className="mock-certificate"><header><Fingerprint size={26} /><span>VERIFEX</span></header><div className="cert-title">Academic credential</div><div className="cert-bar long" /><div className="cert-bar medium" /><div className="cert-bar short" /><div className="cert-mark"><ScanLine size={18} /> Field inspection</div><div className="cert-seal"><ShieldCheck size={30} /></div></div>
          <div className="visual-scanline" /><span className="visual-bottom"><Binary size={16} /> SHA-256  /  ED25519  /  AES-GCM</span>
        </div>
      </section>
      <section className="landing-proof">
        <article><span><ScanLine size={22} /></span><h2>Inspect the document</h2><p>Review extracted fields and visual signs of editing.</p></article>
        <article><span><BrainCircuit size={22} /></span><h2>Trace every AI finding</h2><p>See which engines ran and where the local model marked regions for review.</p></article>
        <article><span><FileCheck2 size={22} /></span><h2>Verify issuer integrity</h2><p>Check the fingerprint, Ed25519 signature, and current revocation status.</p></article>
      </section>
    </main>
  </div>;
}

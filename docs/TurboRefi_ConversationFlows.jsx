import { useState } from "react";

const COLORS = {
  navy: "#1B3A5C",
  teal: "#0D7377",
  amber: "#F57F17",
  green: "#2E7D32",
  red: "#C62828",
  borrower: "#2563EB",
  system: "#6B7280",
  bg: "#FAFBFC",
};

// ── Compliance Score Component ──
function ComplianceScore({ score, breakdown }) {
  const getColor = (s) => (s >= 90 ? COLORS.green : s >= 70 ? COLORS.amber : COLORS.red);
  return (
    <div style={{ background: "#fff", border: `2px solid ${getColor(score)}`, borderRadius: 12, padding: 20, margin: "12px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: getColor(score), display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ color: "#fff", fontWeight: 800, fontSize: 22, fontFamily: "'JetBrains Mono', monospace" }}>{score}</span>
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, color: COLORS.navy }}>Compliance Score</div>
          <div style={{ fontSize: 13, color: "#666" }}>0–100 weighted composite</div>
        </div>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {breakdown.map((b, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 60px 50px 80px", alignItems: "center", fontSize: 13, padding: "6px 0", borderBottom: "1px solid #eee" }}>
            <span style={{ color: "#333" }}>{b.component}</span>
            <span style={{ color: "#888", textAlign: "center" }}>Weight: {b.weight}%</span>
            <span style={{ fontWeight: 700, textAlign: "center", color: getColor(b.score), fontFamily: "'JetBrains Mono', monospace" }}>{b.score}</span>
            <span style={{ fontSize: 11, color: b.status === "PASS" ? COLORS.green : b.status === "FLAG" ? COLORS.amber : COLORS.red, fontWeight: 600, textAlign: "right" }}>
              {b.status === "PASS" ? "✓ PASS" : b.status === "FLAG" ? "⚠ FLAG" : "✗ FAIL"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Chat Bubble ──
function Bubble({ role, children, fnmaRef, toolCall, ragQuery }) {
  const config = {
    borrower: { bg: "#EFF6FF", border: "#BFDBFE", label: "🏠 Borrower", color: COLORS.borrower },
    loa: { bg: "#F0FDFA", border: "#99F6E4", label: "🤖 Loan Officer Agent", color: COLORS.teal },
    system: { bg: "#F3F4F6", border: "#D1D5DB", label: "⚙️ System", color: COLORS.system },
    verifier: { bg: "#FFFBEB", border: "#FDE68A", label: "✅ Verifier Agent", color: COLORS.amber },
  };
  const c = config[role];
  return (
    <div style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: 10, padding: "12px 16px", margin: "8px 0", marginLeft: role === "borrower" ? 0 : 24 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: c.color, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>{c.label}</div>
      <div style={{ fontSize: 14, color: "#1f2937", lineHeight: 1.6 }}>{children}</div>
      {fnmaRef && (
        <div style={{ marginTop: 8, padding: "6px 10px", background: "#EDE9FE", borderRadius: 6, fontSize: 12, color: "#5B21B6" }}>
          📚 <strong>Retrieved:</strong> {fnmaRef}
        </div>
      )}
      {ragQuery && (
        <div style={{ marginTop: 6, padding: "6px 10px", background: "#E0E7FF", borderRadius: 6, fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#3730A3" }}>
          🔍 RAG Query: {ragQuery}
        </div>
      )}
      {toolCall && (
        <div style={{ marginTop: 6, padding: "6px 10px", background: "#ECFDF5", borderRadius: 6, fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: COLORS.green }}>
          🧮 {toolCall}
        </div>
      )}
    </div>
  );
}

// ── Verification Table ──
function VerificationTable({ fields }) {
  return (
    <div style={{ overflowX: "auto", margin: "10px 0" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: COLORS.navy }}>
            {["Field", "LOA Value", "Verifier Value", "Status", "FNMA Section"].map((h) => (
              <th key={h} style={{ color: "#fff", padding: "8px 10px", textAlign: "left", fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={i} style={{ background: i % 2 ? "#f9fafb" : "#fff", borderBottom: "1px solid #e5e7eb" }}>
              <td style={{ padding: "7px 10px", fontWeight: 500 }}>{f.field}</td>
              <td style={{ padding: "7px 10px", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{f.loa}</td>
              <td style={{ padding: "7px 10px", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{f.verifier}</td>
              <td style={{ padding: "7px 10px", fontWeight: 700, color: f.match ? COLORS.green : COLORS.red }}>{f.match ? "✓ MATCH" : "✗ MISMATCH"}</td>
              <td style={{ padding: "7px 10px", fontSize: 12, color: "#6B21A8" }}>{f.ref}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Expanded Verification Walkthrough ──
function ExpandedVerification({ steps }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ margin: "10px 0" }}>
      <button onClick={() => setOpen(!open)} style={{ background: COLORS.amber, color: "#fff", border: "none", borderRadius: 6, padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
        {open ? "▼ Hide" : "▶ Show"} Full Verifier Re-Derivation Walkthrough
      </button>
      {open && (
        <div style={{ marginTop: 10, padding: 16, background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 10 }}>
          {steps.map((s, i) => (
            <div key={i} style={{ marginBottom: 14, paddingBottom: 12, borderBottom: i < steps.length - 1 ? "1px dashed #FDE68A" : "none" }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: COLORS.amber, marginBottom: 4 }}>Step {i + 1}: {s.title}</div>
              <div style={{ fontSize: 13, color: "#333", lineHeight: 1.6, marginBottom: 4 }}>{s.description}</div>
              {s.ragQuery && <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#3730A3", background: "#E0E7FF", padding: "4px 8px", borderRadius: 4, marginBottom: 4 }}>🔍 Independent RAG: {s.ragQuery}</div>}
              {s.toolCall && <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: COLORS.green, background: "#ECFDF5", padding: "4px 8px", borderRadius: 4, marginBottom: 4 }}>🧮 {s.toolCall}</div>}
              {s.result && <div style={{ fontSize: 12, color: "#1f2937", background: "#fff", padding: "6px 10px", borderRadius: 4, border: "1px solid #e5e7eb" }}>{s.result}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════
// UC1: W2 Employee - Rate-Term Refi
// ═══════════════════════════════════
function UC1() {
  return (
    <div>
      <div style={{ padding: "12px 16px", background: "#EFF6FF", borderRadius: 8, marginBottom: 16, borderLeft: `4px solid ${COLORS.borrower}` }}>
        <strong>Scenario:</strong> Sarah Chen — W2 software engineer, $150K/yr, current rate 7.5%, home value $600K, loan balance $450K, 5+ years at employer. Uploads current mortgage statement.
      </div>

      <Bubble role="system">Borrower uploaded: <strong>Mortgage_Statement_Feb2026.pdf</strong>. Extracting data…<br/>→ Extracted: Rate 7.5% | Balance $450,000 | Servicer: Wells Fargo | Loan# 2019-88431 | FNMA-owned | Monthly P&I: $3,146</Bubble>

      <Bubble role="loa" fnmaRef="B3-3.1-01 — General Income Information (income stability, qualifying principles)">
        Welcome, Sarah. I've reviewed your mortgage statement. You're currently at 7.5% on a $450,000 balance serviced by Wells Fargo, and your loan is Fannie Mae-owned. That's a strong starting point for a rate-term refinance.<br/><br/>
        To evaluate your options, I'll need a few items. Could you provide: <strong>(1)</strong> your two most recent paystubs, and <strong>(2)</strong> your most recent W-2?
      </Bubble>

      <Bubble role="borrower">Sure — I make $150K/year base salary at Microsoft. I've been there 6 years. Here are my last two paystubs and W-2.</Bubble>

      <Bubble role="system">Document upload: 2 paystubs + W-2 received. Parsing…<br/>→ Employer: Microsoft Corp | Hire Date: 2020-01-15 | Gross Monthly: $12,500 | YTD Gross: $25,000 (2 months) | W-2 Annual: $150,000</Bubble>

      <Bubble role="loa"
        fnmaRef="B3-3.2-01 — Standards for Employment Documentation (paystub + W-2 requirements)"
        ragQuery='gse="fnma" AND income_type="w2_salary" AND use_case_tags="uc1" → "W2 salaried employee qualifying income verification documentation"'>
        Per FNMA Selling Guide Section B3-3.2-01, your documentation is complete: current paystubs showing YTD earnings consistent with W-2, and employment of 6 years exceeds the 2-year stability requirement in B3-3.1-01. Let me calculate your qualifying income and LTV.
      </Bubble>

      <Bubble role="system"
        toolCall="calc_w2_income(gross_monthly=12500, pay_frequency='monthly', gse='fnma') → annual: $150,000 | monthly_qualifying: $12,500">
        Tool call: W2 Income Calculator
      </Bubble>
      <Bubble role="system"
        toolCall="calc_ltv(loan_amount=450000, property_value=600000) → ltv_ratio: 0.75 | ltv_percent: 75.0%">
        Tool call: LTV Calculator
      </Bubble>

      <Bubble role="loa" fnmaRef="B2-1.3-01 — Eligible LTV/CLTV/HCLTV Ratios (75% LTV well within limits)">
        Here's your assessment, Sarah:<br/><br/>
        <strong>Qualifying Monthly Income:</strong> $12,500<br/>
        <strong>Current LTV:</strong> 75.0% (well below the 80% threshold — no PMI required)<br/>
        <strong>Employment Stability:</strong> 6 years at Microsoft ✓ (exceeds 2-year requirement per B3-3.1-01)<br/>
        <strong>Documentation:</strong> Complete per B3-3.2-01 ✓<br/><br/>
        At current market rates around 6.0%, you'd save approximately <strong>$420/month</strong> on a 30-year fixed refi. I'm packaging this as a Loan Recommendation for verification now.
      </Bubble>

      {/* VERIFIER SECTION */}
      <div style={{ marginTop: 24, padding: 2, background: "linear-gradient(135deg, #FEF3C7, #FDE68A)", borderRadius: 14 }}>
        <div style={{ background: "#fff", borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: COLORS.amber, marginBottom: 12 }}>✅ VERIFIER AGENT — Independent Verification (UC1)</div>

          <VerificationTable fields={[
            { field: "Monthly Qualifying Income", loa: "$12,500", verifier: "$12,500", match: true, ref: "B3-3.1-01" },
            { field: "LTV Ratio", loa: "75.0%", verifier: "75.0%", match: true, ref: "B2-1.3-01" },
            { field: "Employment Duration", loa: "6 years", verifier: "6 years (hire 2020-01-15)", match: true, ref: "B3-3.1-01" },
            { field: "2-Year Stability Met", loa: "Yes", verifier: "Yes", match: true, ref: "B3-3.1-01" },
            { field: "Documentation Complete", loa: "Yes (paystubs + W-2)", verifier: "Yes", match: true, ref: "B3-3.2-01" },
            { field: "PMI Required", loa: "No (LTV < 80%)", verifier: "No", match: true, ref: "B2-1.3-01" },
            { field: "Guideline Sections Cited", loa: "B3-3.1-01, B3-3.2-01, B2-1.3-01", verifier: "B3-3.1-01, B3-3.2-01, B2-1.3-01", match: true, ref: "Audit" },
          ]} />

          <ComplianceScore score={97} breakdown={[
            { component: "Guideline Adherence", weight: 40, score: 98, status: "PASS" },
            { component: "Calculation Accuracy", weight: 30, score: 100, status: "PASS" },
            { component: "Documentation Completeness", weight: 20, score: 95, status: "PASS" },
            { component: "Audit Trail Integrity", weight: 10, score: 90, status: "PASS" },
          ]} />

          <ExpandedVerification steps={[
            { title: "Independent RAG Retrieval", ragQuery: 'gse="fnma" AND income_type="w2_salary" → "salaried employee income qualifying documentation requirements"', description: "Verifier independently queries the vector DB for W2 income guidelines. Retrieves B3-3.1-01 (General Income Information) and B3-3.2-01 (Employment Documentation Standards). Confirms these are the correct sections for a W2 rate-term refi.", result: "✓ Retrieved sections match LOA's citations. No additional sections are required for this use case." },
            { title: "Independent Income Recalculation", toolCall: "calc_w2_income(gross_monthly=12500, pay_frequency='monthly', gse='fnma') → $12,500/month", description: "Verifier re-runs the W2 income calculator with the raw paystub data (not the LOA's output). Confirms monthly qualifying income of $12,500.", result: "✓ MATCH: LOA reported $12,500. Verifier independently calculated $12,500. Delta: $0." },
            { title: "Independent LTV Recalculation", toolCall: "calc_ltv(loan_amount=450000, property_value=600000) → 75.0%", description: "Verifier re-calculates LTV from the raw mortgage statement balance and stated property value.", result: "✓ MATCH: LOA reported 75.0%. Verifier calculated 75.0%. Delta: 0.0%." },
            { title: "Employment Stability Verification", description: "Per B3-3.1-01: 'In most instances, a minimum history of two years of employment income is recommended.' Hire date 2020-01-15 to current date = ~6 years. Exceeds 2-year minimum.", result: "✓ MATCH: Employment stability confirmed. W-2 employer matches paystub employer (Microsoft Corp)." },
            { title: "Documentation Completeness Audit", description: "Per B3-3.2-01: Required docs for W2 income include (1) most recent paystub covering 30 days, (2) W-2 for most recent year. Both provided. Verbal VOE per B3-3.1-07 will be needed within 10 business days of closing (not yet applicable at this stage).", result: "✓ PASS with note: Verbal VOE (B3-3.1-07) required before closing. Documentation score 95/100 (5 points withheld pending VOE)." },
          ]} />
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════
// UC2: W2 Employee - PMI Removal
// ═══════════════════════════════════
function UC2() {
  return (
    <div>
      <div style={{ padding: "12px 16px", background: "#EFF6FF", borderRadius: 8, marginBottom: 16, borderLeft: `4px solid ${COLORS.borrower}` }}>
        <strong>Scenario:</strong> James Wilson — W2 teacher, $75K/yr, current rate 7.25%, original down payment 10%, home appreciated from $350K to $400K, paying $185/mo PMI. Uploads current mortgage statement.
      </div>

      <Bubble role="system">Borrower uploaded: <strong>Mortgage_Statement_Jan2026.pdf</strong>. Extracting data…<br/>→ Extracted: Rate 7.25% | Balance $290,000 | Servicer: US Bank | Loan# 2021-45219 | FHLMC-owned | Monthly P&I: $1,978 | PMI: $185/mo | Original Value: $350,000</Bubble>

      <Bubble role="loa" fnmaRef="B3-3.1-01 — General Income Information + B2-1.3-01 — LTV/PMI Thresholds">
        Hello, James. I see you're at 7.25% with a $290,000 balance and paying $185/month in PMI. Your loan is Freddie Mac-owned, which opens some additional options I'll evaluate.<br/><br/>
        I notice your original home value was $350,000. Do you have a sense of what your home is worth now? A recent appraisal, a Zestimate, or a comparative market analysis would help me assess your equity position.
      </Bubble>

      <Bubble role="borrower">My neighbor's identical home just sold for $405K last month. I'd estimate mine is worth about $400K now. I'm a teacher making $75K/year, same school district for 8 years.</Bubble>

      <Bubble role="system">Borrower provided: Estimated current value $400,000 | Income $75,000/yr | Employment: 8 years same employer. Requesting paystubs + W-2 for income verification.</Bubble>

      <Bubble role="loa"
        ragQuery='gse="fnma" AND use_case_tags="uc2" AND content_type="eligibility_criteria" → "PMI removal LTV threshold refinance equity calculation"'>
        Great — let me run the numbers on both the equity position and the income qualification. I'll also evaluate both the FNMA and FHLMC pathways since your loan is currently Freddie-owned.
      </Bubble>

      <Bubble role="system" toolCall="calc_w2_income(gross_monthly=6250, pay_frequency='monthly', gse='fnma') → annual: $75,000 | monthly_qualifying: $6,250">Tool call: W2 Income Calculator</Bubble>
      <Bubble role="system" toolCall="calc_ltv(loan_amount=290000, property_value=400000) → ltv_ratio: 0.725 | ltv_percent: 72.5%">Tool call: LTV Calculator</Bubble>
      <Bubble role="system" toolCall="calc_pmi_savings(current_pmi_monthly=185, years_remaining=22) → total_savings: $48,840 | monthly_savings: $185">Tool call: PMI Savings Calculator</Bubble>

      <Bubble role="loa" fnmaRef="B2-1.3-01 — LTV ≤ 80% eliminates PMI requirement; current 72.5% qualifies">
        James, great news — your equity position is strong:<br/><br/>
        <strong>Current LTV:</strong> 72.5% (well below the 80% PMI threshold per FNMA B2-1.3-01)<br/>
        <strong>Qualifying Income:</strong> $6,250/month<br/>
        <strong>PMI Elimination Savings:</strong> $185/month ($48,840 over remaining loan life)<br/>
        <strong>Rate Reduction Savings:</strong> At 6.0%, approximately $230/month<br/>
        <strong>Total Combined Savings:</strong> ~$415/month<br/><br/>
        Since your loan is Freddie-owned, I'm also evaluating Freddie Mac's <strong>Refi Possible</strong> program — your $75K income may qualify under the AMI limit. Packaging for verification now.
      </Bubble>

      <div style={{ marginTop: 24, padding: 2, background: "linear-gradient(135deg, #FEF3C7, #FDE68A)", borderRadius: 14 }}>
        <div style={{ background: "#fff", borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: COLORS.amber, marginBottom: 12 }}>✅ VERIFIER AGENT — Independent Verification (UC2)</div>

          <VerificationTable fields={[
            { field: "Monthly Qualifying Income", loa: "$6,250", verifier: "$6,250", match: true, ref: "B3-3.1-01" },
            { field: "LTV Ratio", loa: "72.5%", verifier: "72.5%", match: true, ref: "B2-1.3-01" },
            { field: "PMI Removal Eligible", loa: "Yes (LTV < 80%)", verifier: "Yes", match: true, ref: "B2-1.3-01" },
            { field: "PMI Monthly Savings", loa: "$185", verifier: "$185", match: true, ref: "Calculator" },
            { field: "Employment Duration", loa: "8 years", verifier: "8 years", match: true, ref: "B3-3.1-01" },
            { field: "Property Value Source", loa: "Borrower estimate ($400K)", verifier: "Borrower estimate — flag for appraisal", match: true, ref: "B4-1.3-04" },
            { field: "Refi Possible Eligibility", loa: "Potentially eligible", verifier: "Requires AMI lookup for property ZIP", match: true, ref: "FHLMC Refi Possible" },
          ]} />

          <ComplianceScore score={91} breakdown={[
            { component: "Guideline Adherence", weight: 40, score: 95, status: "PASS" },
            { component: "Calculation Accuracy", weight: 30, score: 100, status: "PASS" },
            { component: "Documentation Completeness", weight: 20, score: 78, status: "FLAG" },
            { component: "Audit Trail Integrity", weight: 10, score: 88, status: "PASS" },
          ]} />

          <ExpandedVerification steps={[
            { title: "Independent RAG Retrieval", ragQuery: 'gse="fnma" AND use_case_tags="uc2" AND content_type="eligibility_criteria" → "LTV PMI threshold refinance elimination"', description: "Verifier independently retrieves B2-1.3-01 (LTV eligibility matrices) and B3-3.1-01 (income qualification). Confirms 80% LTV is the PMI threshold for conventional loans.", result: "✓ Retrieved sections match. B2-1.3-01 confirms: 'Borrower-paid MI is not required when LTV ≤ 80%.' Current 72.5% qualifies." },
            { title: "Independent LTV Recalculation", toolCall: "calc_ltv(loan_amount=290000, property_value=400000) → 72.5%", description: "Verifier re-calculates LTV from raw mortgage statement balance ($290,000) and borrower's stated value ($400,000).", result: "✓ MATCH: 72.5%. However, Verifier flags that property value is a borrower estimate, not an appraisal. Per B4-1.3-04, a formal appraisal will be required at closing. Compliance note: score reduced by 5 points for documentation gap." },
            { title: "PMI Savings Recalculation", toolCall: "calc_pmi_savings(current_pmi_monthly=185, years_remaining=22) → total: $48,840", description: "Verifier confirms PMI savings calculation. $185/month × 264 remaining months = $48,840.", result: "✓ MATCH: PMI savings confirmed at $185/month, $48,840 total." },
            { title: "Refi Possible Eligibility Check", ragQuery: 'gse="fhlmc" AND product_type="refi_possible" → "Refi Possible income AMI limit eligibility"', description: "Verifier retrieves the Refi Possible product sheet. Confirms: total annual qualifying income must not exceed 100% AMI for the property location. $75K income must be checked against the specific ZIP code's AMI. Loan must be currently Freddie-owned (confirmed from statement).", result: "⚠ FLAG: AMI check is location-dependent. LOA correctly identified potential eligibility but did not perform the AMI lookup. Recommend completing AMI verification in next step." },
            { title: "Documentation Completeness Audit", description: "Per B3-3.2-01: Paystubs + W-2 required (received). Per B3-3.1-07: Verbal VOE required before closing (not yet due). Per B4-1.3-04: Formal appraisal needed to confirm $400K value (not yet ordered). Documentation completeness score: 78/100 (appraisal pending, AMI lookup pending).", result: "⚠ FLAG: Two items outstanding — (1) formal appraisal, (2) AMI lookup for Refi Possible. Core eligibility confirmed but final documentation incomplete." },
          ]} />
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════
// UC3: Self-Employed - Rate-Term Refi
// ═══════════════════════════════════
function UC3() {
  return (
    <div>
      <div style={{ padding: "12px 16px", background: "#EFF6FF", borderRadius: 8, marginBottom: 16, borderLeft: `4px solid ${COLORS.borrower}` }}>
        <strong>Scenario:</strong> Maria Garcia — Freelance graphic designer (sole proprietor), Year 1 net $95K, Year 2 net $110K, depreciation addback $8K, current rate 6.75%, home value $520K, balance $380K. Uploads mortgage statement.
      </div>

      <Bubble role="system">Borrower uploaded: <strong>Mortgage_Statement_Feb2026.pdf</strong>. Extracting data…<br/>→ Extracted: Rate 6.75% | Balance $380,000 | Servicer: PennyMac | Loan# 2020-71033 | FNMA-owned | Monthly P&I: $2,464</Bubble>

      <Bubble role="loa" fnmaRef="B3-3.3-01 — Underwriting Factors and Documentation for SE Borrowers">
        Hello, Maria. I see you're at 6.75% with a $380,000 balance on an FNMA-owned loan. Let me help you evaluate a rate reduction.<br/><br/>
        Since you're self-employed, I'll need additional documentation beyond what a W-2 employee provides. Per FNMA Section B3-3.3-01, could you please provide:<br/>
        <strong>(1)</strong> Your 2 most recent years of personal federal tax returns (1040) with all schedules<br/>
        <strong>(2)</strong> Schedule C for your graphic design business (both years)<br/>
        <strong>(3)</strong> A current profit-and-loss statement if available
      </Bubble>

      <Bubble role="borrower">I've been freelancing for 4 years. Here are my 2024 and 2023 tax returns. Year 1 (2023): net income $95K with $4K depreciation. Year 2 (2024): net income $110K with $4K depreciation. Business is growing.</Bubble>

      <Bubble role="system">Documents received: 2023 + 2024 Form 1040 with Schedule C.<br/>→ Parsed: 2023 Net: $95,000, Depreciation: $4,000 | 2024 Net: $110,000, Depreciation: $4,000 | Business: Garcia Design LLC (sole prop) | 4 years operating</Bubble>

      <Bubble role="loa"
        fnmaRef="B3-3.3-03 — Income Analysis: Individual Tax Returns (Schedule C analysis, 2-year averaging)"
        ragQuery='gse="fnma" AND income_type="self_employed" AND content_type="formula" → "self employed income averaging Schedule C depreciation addback"'>
        Good — your income trend is positive (growing from $95K to $110K), which is favorable. Per B3-3.3-03, I need to perform a 2-year income averaging calculation with addbacks for non-cash expenses. Let me run this.
      </Bubble>

      <Bubble role="system" toolCall="calc_self_employed_income(yr1_net=95000, yr2_net=110000, depreciation=8000, depletion=0, gse='fnma') → qualifying_monthly: $8,875">Tool call: Self-Employed Income Calculator<br/>Formula: ($95,000 + $110,000 + $8,000 addback) / 24 months = $8,875/month</Bubble>
      <Bubble role="system" toolCall="calc_ltv(loan_amount=380000, property_value=520000) → ltv_percent: 73.1%">Tool call: LTV Calculator</Bubble>

      <Bubble role="loa" fnmaRef="B3-3.3-01 — Business must be verified as operational; B3-3.1-01 — Income stability and continuance (4-year history exceeds 2-year min)">
        Maria, here's your complete assessment:<br/><br/>
        <strong>Qualifying Monthly Income:</strong> $8,875 (2-year average with $8K depreciation addback per B3-3.3-03)<br/>
        <strong>Income Trend:</strong> Positive (+15.8% year-over-year) ✓<br/>
        <strong>Current LTV:</strong> 73.1% (no PMI required)<br/>
        <strong>Business Longevity:</strong> 4 years (exceeds 2-year requirement per B3-3.3-01)<br/>
        <strong>Documentation:</strong> 2 years tax returns + Schedule C ✓<br/><br/>
        At a target rate of 6.0%, estimated monthly savings of ~$200. Note: per B3-3.3-01, your business existence must be independently verified (phone listing, CPA letter, or business license). Packaging for verification.
      </Bubble>

      <div style={{ marginTop: 24, padding: 2, background: "linear-gradient(135deg, #FEF3C7, #FDE68A)", borderRadius: 14 }}>
        <div style={{ background: "#fff", borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: COLORS.amber, marginBottom: 12 }}>✅ VERIFIER AGENT — Independent Verification (UC3)</div>

          <VerificationTable fields={[
            { field: "Monthly Qualifying Income", loa: "$8,875", verifier: "$8,875", match: true, ref: "B3-3.3-03" },
            { field: "Year 1 Net Income", loa: "$95,000", verifier: "$95,000", match: true, ref: "Schedule C" },
            { field: "Year 2 Net Income", loa: "$110,000", verifier: "$110,000", match: true, ref: "Schedule C" },
            { field: "Depreciation Addback", loa: "$8,000 (2yr total)", verifier: "$8,000", match: true, ref: "B3-3.3-03" },
            { field: "Income Trend", loa: "Positive (+15.8%)", verifier: "Positive (+15.8%)", match: true, ref: "B3-3.3-03" },
            { field: "LTV Ratio", loa: "73.1%", verifier: "73.1%", match: true, ref: "B2-1.3-01" },
            { field: "Business Verification", loa: "Required (noted)", verifier: "Required — not yet completed", match: true, ref: "B3-3.3-01" },
            { field: "Declining Income Check", loa: "Not declining", verifier: "Confirmed: +$15K YoY", match: true, ref: "B3-3.3-03" },
          ]} />

          <ComplianceScore score={93} breakdown={[
            { component: "Guideline Adherence", weight: 40, score: 96, status: "PASS" },
            { component: "Calculation Accuracy", weight: 30, score: 100, status: "PASS" },
            { component: "Documentation Completeness", weight: 20, score: 80, status: "FLAG" },
            { component: "Audit Trail Integrity", weight: 10, score: 92, status: "PASS" },
          ]} />

          <ExpandedVerification steps={[
            { title: "Independent RAG Retrieval for SE Income", ragQuery: 'gse="fnma" AND income_type="self_employed" AND section_id="B3-3.3-03" → "self employed income analysis individual tax returns Schedule C averaging"', description: "Verifier independently retrieves B3-3.3-03 (Income Analysis: Individual Tax Returns). Confirms the 2-year averaging methodology and depreciation addback rules. Also retrieves B3-3.3-01 for business verification requirements.", result: "✓ Retrieved B3-3.3-03 and B3-3.3-01. LOA correctly identified both sections. Verifier confirms the averaging formula: (Year1 Net + Year2 Net + Total Addbacks) / 24." },
            { title: "Independent Income Recalculation", toolCall: "calc_self_employed_income(yr1_net=95000, yr2_net=110000, depreciation=8000, depletion=0, gse='fnma') → $8,875/month", description: "Verifier re-derives from raw tax return data. Schedule C Year 1: $95,000 net. Schedule C Year 2: $110,000 net. Depreciation addback: $4,000/yr × 2 = $8,000. Total: ($95,000 + $110,000 + $8,000) = $213,000 / 24 = $8,875.00.", result: "✓ MATCH: LOA reported $8,875. Verifier calculated $8,875. Delta: $0. Addback items correctly limited to depreciation per B3-3.3-03." },
            { title: "Declining Income Analysis", description: "Per B3-3.3-03: If the trend in the amount of income is declining, the lender must document and explain why the income can be expected to remain stable. Year 1 → Year 2 change: $95K → $110K = +$15,000 (+15.8%). Income is INCREASING, not declining. No declining income concern.", result: "✓ PASS: Income trend is positive. No additional documentation required for income stability." },
            { title: "Business Verification Check", ragQuery: 'gse="fnma" AND section_id="B3-3.3-01" AND content_type="documentation_requirement" → "self employment business verification existence"', description: "Per B3-3.3-01: The lender must verify the existence of the borrower's business within 120 days of the Note date. Methods: phone listing, business license, CPA letter, or third-party verification. LOA noted this requirement but it has not been completed yet.", result: "⚠ FLAG: Business verification pending. This is a pre-closing requirement, not blocking at this stage, but must be completed before closing. Documentation score reduced by 10 points." },
            { title: "Tax Return Completeness Audit", description: "Per B3-3.1-02: Tax returns must be the most recently filed, complete with all schedules. Verified: 2023 and 2024 returns received with Schedule C. W-2s from 1040 are not applicable (no W-2 employment). IRS Form 4506-C (per B3-3.1-06) will be needed to validate returns against IRS transcripts.", result: "✓ PASS with note: 4506-C/IRS transcript validation required before closing. Tax returns are complete for current analysis." },
          ]} />
        </div>
      </div>
    </div>
  );
}

// ── Main App ──
export default function App() {
  const [tab, setTab] = useState("uc1");
  const tabs = [
    { id: "uc1", label: "UC1: W2 Rate-Term", color: "#2563EB" },
    { id: "uc2", label: "UC2: PMI Removal", color: "#059669" },
    { id: "uc3", label: "UC3: Self-Employed", color: "#7C3AED" },
  ];

  return (
    <div style={{ fontFamily: "'DM Sans', -apple-system, sans-serif", maxWidth: 820, margin: "0 auto", padding: "24px 16px", background: COLORS.bg, minHeight: "100vh" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet" />

      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: COLORS.navy, margin: 0, letterSpacing: -0.5 }}>TurboRefi Conversation Flows</h1>
        <p style={{ fontSize: 14, color: "#666", marginTop: 6 }}>Loan Officer Agent → Verifier Agent — UC1, UC2, UC3 with FNMA Section References</p>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, borderBottom: "2px solid #e5e7eb", paddingBottom: 2 }}>
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: "10px 20px", fontSize: 13, fontWeight: tab === t.id ? 700 : 500, border: "none",
            borderBottom: tab === t.id ? `3px solid ${t.color}` : "3px solid transparent",
            background: tab === t.id ? `${t.color}10` : "transparent",
            color: tab === t.id ? t.color : "#666", cursor: "pointer", borderRadius: "8px 8px 0 0", transition: "all 0.2s",
          }}>{t.label}</button>
        ))}
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 16, fontSize: 12, color: "#666" }}>
        <span>🏠 <strong style={{ color: COLORS.borrower }}>Borrower</strong></span>
        <span>🤖 <strong style={{ color: COLORS.teal }}>Loan Officer Agent</strong></span>
        <span>⚙️ <strong style={{ color: COLORS.system }}>System / Tool Call</strong></span>
        <span>✅ <strong style={{ color: COLORS.amber }}>Verifier Agent</strong></span>
        <span>📚 <span style={{ color: "#5B21B6" }}>FNMA Section Ref</span></span>
        <span>🔍 <span style={{ color: "#3730A3" }}>RAG Query</span></span>
        <span>🧮 <span style={{ color: COLORS.green }}>Tool Call</span></span>
      </div>

      {/* Content */}
      {tab === "uc1" && <UC1 />}
      {tab === "uc2" && <UC2 />}
      {tab === "uc3" && <UC3 />}
    </div>
  );
}

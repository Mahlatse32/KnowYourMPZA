import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ExternalLink, Search, ShieldCheck } from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type Party = { id: string; name: string; short_name: string };
type Source = { name: string; url?: string };
type Politician = {
  id: string;
  full_name: string;
  display_name: string;
  slug: string;
  profile_url?: string;
  photo_url?: string;
  source_status?: string;
  party?: Party;
};
type CommitteeMembership = { id: string; role?: string; source_url: string; committee: { id: string; name: string } };
type DocumentRead = {
  id: string;
  title: string;
  document_type: string;
  source_url: string;
  publication_date?: string;
  committee_name?: string;
  source?: Source;
};
type DocumentMention = { id: string; snippet: string; confidence_score: number; match_reason?: string; document: DocumentRead };
type DocumentDetail = DocumentRead & { mentions: Array<{ id: string; snippet: string; confidence_score: number; match_reason?: string; politician: Politician }> };
type Question = {
  id: string;
  title: string;
  asked_by_name?: string;
  department?: string;
  status?: string;
  source_url: string;
  asked_date?: string;
  question_text?: string;
  answer_text?: string;
};
type QuestionDetail = Question & { mentions: Array<{ id: string; snippet?: string; confidence_score?: number; match_reason?: string; politician: Politician }> };
type AttendanceSummary = {
  totals: { present: number; absent: number; apology: number; unknown: number };
  recorded_meetings: number;
  by_committee: Array<{ committee_id?: string; committee_name?: string; present: number; absent: number; apology: number; unknown: number; total: number }>;
  recent: Array<{ meeting_id: string; meeting_title: string; meeting_date?: string; committee_name?: string; attendance_status: string; source_url?: string }>;
};

function App() {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    const onPop = () => setPath(location.pathname);
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);
  const route = useMemo(() => path.split("/").filter(Boolean), [path]);
  const navigate = (to: string) => {
    history.pushState(null, "", to);
    setPath(to);
  };
  return (
    <div className="min-h-screen bg-paper text-ink">
      <Header navigate={navigate} />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {route.length === 0 && <Home navigate={navigate} />}
        {route[0] === "search" && <SearchPage navigate={navigate} />}
        {route[0] === "politicians" && (route[1] ? <PoliticianPage id={route[1]} /> : <ListPage title="MPs" endpoint="/politicians" render={(item: Politician) => <PoliticianCard item={item} navigate={navigate} />} />)}
        {route[0] === "parties" && <ListPage title="Parties" endpoint="/parties" render={(item: Party) => <BasicCard title={item.name} meta={item.short_name} />} />}
        {route[0] === "committees" && <ListPage title="Committees" endpoint="/committees" render={(item: { id: string; name: string; source_url?: string }) => <BasicCard title={item.name} link={item.source_url} />} />}
        {route[0] === "documents" && (route[1] ? <DocumentPage id={route[1]} /> : <ListPage title="Documents" endpoint="/documents" render={(item: DocumentRead) => <DocumentCard item={item} navigate={navigate} />} />)}
        {route[0] === "questions" && (route[1] ? <QuestionPage id={route[1]} /> : <ListPage title="Parliamentary Questions" endpoint="/questions" render={(item: Question) => <QuestionCard item={item} navigate={navigate} />} />)}
        {route[0] === "quality" && <QualityPage />}
      </main>
    </div>
  );
}

function Header({ navigate }: { navigate: (to: string) => void }) {
  const links = [["/search", "Search"], ["/politicians", "MPs"], ["/parties", "Parties"], ["/committees", "Committees"], ["/documents", "Documents"], ["/questions", "Questions"], ["/quality", "Quality"]];
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <button onClick={() => navigate("/")} className="text-left text-xl font-semibold text-civic">KnowYourMPZA</button>
        <nav className="flex flex-wrap gap-2 text-sm">
          {links.map(([href, label]) => <button key={href} onClick={() => navigate(href)} className="rounded border border-line px-3 py-1.5 hover:border-civic">{label}</button>)}
        </nav>
      </div>
    </header>
  );
}

function Home({ navigate }: { navigate: (to: string) => void }) {
  return (
    <section className="grid gap-6 lg:grid-cols-[1.3fr_.7fr]">
      <div>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-normal">Evidence-backed South African MP profiles</h1>
        <p className="mt-4 max-w-2xl text-lg text-slate-700">Browse MPs, parties, committees, PMG evidence, parliamentary questions, source links, and quality checks from the verified backend dataset.</p>
        <div className="mt-6 flex gap-3">
          <button onClick={() => navigate("/search")} className="inline-flex items-center gap-2 rounded bg-civic px-4 py-2 text-white"><Search size={18} /> Search MPs</button>
          <button onClick={() => navigate("/quality")} className="inline-flex items-center gap-2 rounded border border-line px-4 py-2"><ShieldCheck size={18} /> Quality</button>
        </div>
      </div>
      <QualitySummary compact />
    </section>
  );
}

function SearchPage({ navigate }: { navigate: (to: string) => void }) {
  const [query, setQuery] = useState("");
  const { data, loading } = useApi<Politician[]>(query ? `/search?name=${encodeURIComponent(query)}` : null);
  return (
    <section>
      <h1 className="section-title">Search MPs</h1>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name, alias, party signal" className="mb-4 w-full rounded border border-line bg-white px-4 py-3" />
      {loading && <p>Loading...</p>}
      <div className="grid gap-3 md:grid-cols-2">{data?.map((item) => <PoliticianCard key={item.id} item={item} navigate={navigate} />)}</div>
    </section>
  );
}

function PoliticianPage({ id }: { id: string }) {
  const { data: person } = useApi<Politician>(`/politicians/${id}`);
  const { data: committees } = useApi<CommitteeMembership[]>(`/politicians/${id}/committees`);
  const { data: attendance } = useApi<AttendanceSummary>(`/politicians/${id}/attendance`);
  const { data: documents } = useApi<DocumentMention[]>(`/politicians/${id}/documents?limit=20`);
  const { data: questions } = useApi<Question[]>(`/politicians/${id}/questions?limit=20`);
  if (!person) return <p>Loading...</p>;
  return (
    <section className="grid gap-6 lg:grid-cols-[.7fr_1.3fr]">
      <div className="rounded border border-line bg-white p-4">
        {person.photo_url && <img src={person.photo_url} alt={person.display_name} className="mb-4 aspect-square w-40 rounded object-cover" />}
        <h1 className="text-2xl font-semibold">{person.full_name}</h1>
        <p className="text-slate-700">{person.party?.name}</p>
        <EvidenceLink href={person.profile_url} label="People's Assembly profile" />
      </div>
      <div className="space-y-5">
        <Panel title="Committees">{committees?.map((item) => <BasicCard key={item.id} title={item.committee.name} meta={item.role || "Member"} link={item.source_url} />)}</Panel>
        <AttendancePanel data={attendance} />
        <Panel title="PMG Evidence">{documents?.map((item) => <DocumentCard key={item.id} item={item.document} snippet={item.snippet} />)}</Panel>
        <Panel title="Parliamentary Questions">{questions?.map((item) => <QuestionCard key={item.id} item={item} />)}</Panel>
      </div>
    </section>
  );
}

function AttendancePanel({ data }: { data: AttendanceSummary | null }) {
  if (!data) return <Panel title="Committee Attendance"><p className="text-sm text-slate-600">Loading...</p></Panel>;
  if (data.recorded_meetings === 0) {
    return (
      <Panel title="Committee Attendance">
        <p className="rounded border border-line bg-white p-4 text-sm text-slate-700">
          No attendance records have been linked to this MP yet. Historical meeting records are still being imported and linked.
        </p>
      </Panel>
    );
  }
  const { totals } = data;
  return (
    <Panel title="Committee Attendance">
      <article className="rounded border border-line bg-white p-4">
        <p className="text-sm text-slate-700">
          Recorded in <span className="font-semibold">{data.recorded_meetings}</span> meeting attendance records:{" "}
          <span className="font-semibold">{totals.present}</span> present, <span className="font-semibold">{totals.apology}</span> apologies,{" "}
          <span className="font-semibold">{totals.absent}</span> absent{totals.unknown > 0 ? `, ${totals.unknown} unrecorded` : ""}.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Counts cover only explicit PMG attendance records linked to this MP so far. Historical meetings are still being imported, so this is not yet a complete attendance rate.
        </p>
      </article>
      {data.by_committee.slice(0, 8).map((row, index) => (
        <article key={row.committee_id || `${row.committee_name}-${index}`} className="rounded border border-line bg-white p-4">
          <h3 className="text-sm font-semibold">{row.committee_name || "Committee not yet linked"}</h3>
          <p className="mt-1 text-sm text-slate-700">{row.present} present | {row.apology} apologies | {row.absent} absent | {row.total} recorded</p>
        </article>
      ))}
      {data.recent.slice(0, 5).map((meeting) => (
        <article key={meeting.meeting_id} className="rounded border border-line bg-white p-4">
          <h3 className="text-sm font-semibold">{meeting.meeting_title}</h3>
          <p className="mt-1 text-sm text-slate-700">{[meeting.meeting_date, meeting.committee_name, meeting.attendance_status].filter(Boolean).join(" | ")}</p>
          <EvidenceLink href={meeting.source_url} />
        </article>
      ))}
    </Panel>
  );
}

function QualityPage() {
  return (
    <section>
      <h1 className="section-title">Quality</h1>
      <QualitySummary />
      <IssuePanel />
    </section>
  );
}

function DocumentPage({ id }: { id: string }) {
  const { data } = useApi<DocumentDetail>(`/documents/${id}`);
  if (!data) return <p>Loading...</p>;
  return <section><h1 className="section-title">{data.title}</h1><BasicCard title={data.document_type} meta={[data.publication_date, data.committee_name].filter(Boolean).join(" | ")} link={data.source_url} /><Panel title="Mentioned MPs">{data.mentions.map((item) => <BasicCard key={item.id} title={item.politician.display_name} meta={`${item.match_reason || "match"} | ${item.confidence_score}`} extra={item.snippet} />)}</Panel></section>;
}

function QuestionPage({ id }: { id: string }) {
  const { data } = useApi<QuestionDetail>(`/questions/${id}`);
  if (!data) return <p>Loading...</p>;
  return <section><h1 className="section-title">{data.title}</h1><BasicCard title={data.asked_by_name || "Question"} meta={[data.department, data.status, data.asked_date].filter(Boolean).join(" | ")} link={data.source_url} /><Panel title="Question"><p className="rounded border border-line bg-white p-4">{data.question_text || "No extracted question text."}</p></Panel><Panel title="Answer"><p className="rounded border border-line bg-white p-4">{data.answer_text || "No extracted answer text."}</p></Panel></section>;
}

function ListPage<T>({ title, endpoint, render }: { title: string; endpoint: string; render: (item: T) => React.ReactNode }) {
  const { data, loading } = useApi<T[]>(`${endpoint}?limit=100`);
  return <section><h1 className="section-title">{title}</h1>{loading && <p>Loading...</p>}<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{data?.map((item, index) => <React.Fragment key={index}>{render(item)}</React.Fragment>)}</div></section>;
}

function QualitySummary({ compact = false }: { compact?: boolean }) {
  const { data } = useApi<Record<string, number>>("/quality/summary");
  const keys = ["total_politicians", "total_parties", "total_committees", "total_committee_memberships", "total_documents", "total_document_mentions", "total_parliamentary_questions", "unresolved_entities_open"];
  return <div className="grid gap-3 rounded border border-line bg-white p-4 sm:grid-cols-2">{keys.map((key) => <div key={key}><p className="text-sm text-slate-600">{key.replaceAll("_", " ")}</p><p className={compact ? "text-2xl font-semibold" : "text-3xl font-semibold"}>{data?.[key] ?? "..."}</p></div>)}</div>;
}

function IssuePanel() {
  const { data } = useApi<Record<string, unknown[]>>("/quality/issues?limit=20");
  return <div className="mt-6 grid gap-3 lg:grid-cols-2">{Object.entries(data || {}).map(([key, value]) => <BasicCard key={key} title={key.replaceAll("_", " ")} meta={`${value.length} items`} />)}</div>;
}

function PoliticianCard({ item, navigate }: { item: Politician; navigate: (to: string) => void }) {
  return <button onClick={() => navigate(`/politicians/${item.id}`)} className="rounded border border-line bg-white p-4 text-left hover:border-civic"><h2 className="font-semibold">{item.display_name}</h2><p className="text-sm text-slate-700">{item.party?.short_name || item.source_status || "MP"}</p></button>;
}

function DocumentCard({ item, snippet, navigate }: { item: DocumentRead; snippet?: string; navigate?: (to: string) => void }) {
  return <article className="rounded border border-line bg-white p-4"><button onClick={() => navigate?.(`/documents/${item.id}`)} className="text-left font-semibold hover:text-civic">{item.title}</button><p className="mt-1 text-sm text-slate-700">{[item.document_type, item.publication_date, item.committee_name].filter(Boolean).join(" | ")}</p>{snippet && <p className="mt-2 text-sm">{snippet}</p>}<EvidenceLink href={item.source_url} /></article>;
}

function QuestionCard({ item, navigate }: { item: Question; navigate?: (to: string) => void }) {
  return <article className="rounded border border-line bg-white p-4"><button onClick={() => navigate?.(`/questions/${item.id}`)} className="text-left font-semibold hover:text-civic">{item.title}</button><p className="mt-1 text-sm text-slate-700">{[item.department, item.status, item.asked_date].filter(Boolean).join(" | ")}</p><EvidenceLink href={item.source_url} /></article>;
}

function BasicCard({ title, meta, link, extra }: { title: string; meta?: string; link?: string; extra?: string }) {
  return <article className="rounded border border-line bg-white p-4"><h2 className="font-semibold">{title}</h2>{meta && <p className="mt-1 text-sm text-slate-700">{meta}</p>}{extra && <p className="mt-2 text-sm">{extra}</p>}<EvidenceLink href={link} /></article>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h2 className="mb-2 text-lg font-semibold">{title}</h2><div className="grid gap-3">{children}</div></section>;
}

function EvidenceLink({ href, label = "Source" }: { href?: string; label?: string }) {
  if (!href) return null;
  return <a href={href} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-civic hover:underline">{label}<ExternalLink size={14} /></a>;
}

function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!path) {
      setData(null);
      return;
    }
    setLoading(true);
    fetch(`${API_BASE}${path}`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(response.statusText)))
      .then(setData)
      .finally(() => setLoading(false));
  }, [path]);
  return { data, loading };
}

createRoot(document.getElementById("root")!).render(<App />);

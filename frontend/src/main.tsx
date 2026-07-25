import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ExternalLink, MessageSquareText, Search, ShieldCheck } from "lucide-react";
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
type AiSource = { title: string; source_url?: string; source_type: string; record_id: string; date?: string; excerpt?: string };
type AiAnswer = {
  id?: string;
  question: string;
  answer: string;
  intent: string;
  sources: AiSource[];
  coverage_notice: string;
  data_snapshot: Record<string, number>;
  model_used: string;
  cached: boolean;
  generated_at: string;
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
        {route[0] === "ask" && <AskPage />}
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
  const links = [["/ask", "Ask"], ["/search", "Search"], ["/politicians", "MPs"], ["/parties", "Parties"], ["/committees", "Committees"], ["/documents", "Documents"], ["/questions", "Questions"], ["/quality", "Quality"]];
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
          <button onClick={() => navigate("/ask")} className="inline-flex items-center gap-2 rounded bg-civic px-4 py-2 text-white"><MessageSquareText size={18} /> Ask</button>
          <button onClick={() => navigate("/search")} className="inline-flex items-center gap-2 rounded bg-civic px-4 py-2 text-white"><Search size={18} /> Search MPs</button>
          <button onClick={() => navigate("/quality")} className="inline-flex items-center gap-2 rounded border border-line px-4 py-2"><ShieldCheck size={18} /> Quality</button>
        </div>
      </div>
      <QualitySummary compact />
    </section>
  );
}

function AskPage() {
  const examples = [
    "Which MPs asked questions about Eskom?",
    "Who sits on the police committee?",
    "Show questions mentioning illegal immigration.",
    "Which bills mention policing?",
  ];
  const [question, setQuestion] = useState(examples[0]);
  const [answer, setAnswer] = useState<AiAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = (refresh = false) => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/ai/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, refresh }),
    })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(response.statusText)))
      .then(setAnswer)
      .catch((err: Error) => {
        setAnswer(null);
        setError(err.message || "Ask failed");
      })
      .finally(() => setLoading(false));
  };

  return (
    <section className="grid gap-6 lg:grid-cols-[.9fr_1.1fr]">
      <div>
        <h1 className="section-title">Ask KnowYourMPZA</h1>
        <p className="mb-4 text-sm text-slate-700">Ask in normal language. Answers are generated only from source-backed records currently imported into KnowYourMPZA.</p>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} className="min-h-32 w-full rounded border border-line bg-white px-4 py-3" />
        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={() => ask(false)} disabled={loading} className="inline-flex items-center gap-2 rounded bg-civic px-4 py-2 text-white disabled:opacity-60"><MessageSquareText size={18} /> Ask</button>
          {answer && <button onClick={() => ask(true)} disabled={loading} className="rounded border border-line px-4 py-2 disabled:opacity-60">Refresh answer</button>}
        </div>
        <div className="mt-5 grid gap-2">
          {examples.map((item) => <button key={item} onClick={() => setQuestion(item)} className="rounded border border-line bg-white px-3 py-2 text-left text-sm hover:border-civic">{item}</button>)}
        </div>
      </div>
      <div className="space-y-4">
        {loading && <LoadingText />}
        {error && <EmptyState title="AI answer unavailable" body="The backend could not generate a source-backed answer. Existing search and browse pages remain available." />}
        {answer && (
          <>
            <article className="rounded border border-line bg-white p-4">
              <div className="mb-2 flex flex-wrap gap-2 text-xs text-slate-600">
                <span className="rounded border border-line px-2 py-1">{answer.intent}</span>
                <span className="rounded border border-line px-2 py-1">{answer.cached ? "saved answer" : "fresh answer"}</span>
                <span className="rounded border border-line px-2 py-1">{answer.model_used}</span>
              </div>
              <p className="whitespace-pre-line text-sm leading-6">{answer.answer}</p>
            </article>
            <p className="rounded border border-line bg-white p-3 text-sm text-slate-700">{answer.coverage_notice}</p>
            <Panel title="Sources">
              {answer.sources.length > 0 ? answer.sources.map((source) => (
                <article key={`${source.source_type}-${source.record_id}`} className="rounded border border-line bg-white p-4">
                  <h3 className="font-semibold">{source.title}</h3>
                  <p className="mt-1 text-sm text-slate-700">{[source.source_type, source.date].filter(Boolean).join(" | ")}</p>
                  {source.excerpt && <p className="mt-2 text-sm">{source.excerpt}</p>}
                  <EvidenceLink href={source.source_url} />
                </article>
              )) : <EmptyState title="No source-backed match yet" body="The AI layer did not find imported records for this question, so it refused to invent an answer." />}
            </Panel>
          </>
        )}
        {!answer && !loading && !error && <EmptyState title="No question answered yet" body="Ask a civic question to search across MPs, committees, questions, bills, attendance, and votes." />}
      </div>
    </section>
  );
}

function SearchPage({ navigate }: { navigate: (to: string) => void }) {
  const [query, setQuery] = useState("");
  const { data, loading, error } = useApi<Politician[]>(query ? `/search?name=${encodeURIComponent(query)}` : null);
  return (
    <section>
      <h1 className="section-title">Search MPs</h1>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name, alias, party signal" className="mb-4 w-full rounded border border-line bg-white px-4 py-3" />
      {loading && <LoadingText />}
      {error && <EmptyState title="Search is unavailable" body="The API did not return search results. Source-backed profile pages remain unchanged; try again after the backend is healthy." />}
      {query && data?.length === 0 && <EmptyState title="No matching MPs found" body="Only source-backed politician identities currently in the production dataset are searchable." />}
      <div className="grid gap-3 md:grid-cols-2">{data?.map((item) => <PoliticianCard key={item.id} item={item} navigate={navigate} />)}</div>
    </section>
  );
}

function PoliticianPage({ id }: { id: string }) {
  const { data: person, error: personError } = useApi<Politician>(`/politicians/${id}`);
  const { data: committees } = useApi<CommitteeMembership[]>(`/politicians/${id}/committees`);
  const { data: attendance } = useApi<AttendanceSummary>(`/politicians/${id}/attendance`);
  const { data: documents } = useApi<DocumentMention[]>(`/politicians/${id}/documents?limit=20`);
  const { data: questions } = useApi<Question[]>(`/politicians/${id}/questions?limit=20`);
  if (personError) return <EmptyState title="MP profile unavailable" body="The backend could not load this profile. No fallback or inferred record is shown." />;
  if (!person) return <LoadingText />;
  const partyLabel = confirmedPartyLabel(person.party);
  return (
    <section className="grid gap-6 lg:grid-cols-[.7fr_1.3fr]">
      <div className="rounded border border-line bg-white p-4">
        {person.photo_url && <img src={person.photo_url} alt={person.display_name} className="mb-4 aspect-square w-40 rounded object-cover" />}
        <h1 className="text-2xl font-semibold">{person.full_name}</h1>
        <p className="text-slate-700">{partyLabel}</p>
        {!person.party || isUnknownParty(person.party) ? <p className="mt-2 text-sm text-slate-600">Party is not confirmed from the currently linked production records.</p> : null}
        <EvidenceLink href={person.profile_url} label="Source profile" />
      </div>
      <div className="space-y-5">
        <CoverageNotice />
        <Panel title="Committees">
          {committees === null ? <LoadingText /> : committees.length > 0 ? committees.map((item) => <BasicCard key={item.id} title={item.committee.name} meta={item.role || "Member"} link={item.source_url} />) : <EmptyState title="No linked committees yet" body="Committee memberships appear only when source records explicitly link this MP to a committee. Meeting backfill may still add links." />}
        </Panel>
        <AttendancePanel data={attendance} />
        <Panel title="PMG Evidence">
          {documents === null ? <LoadingText /> : documents.length > 0 ? documents.map((item) => <DocumentCard key={item.id} item={item.document} snippet={item.snippet} />) : <EmptyState title="No linked PMG evidence yet" body="PMG documents are shown only when the mention can be linked to this MP with source evidence." />}
        </Panel>
        <Panel title="Parliamentary Questions">
          {questions === null ? <LoadingText /> : questions.length > 0 ? questions.map((item) => <QuestionCard key={item.id} item={item} />) : <EmptyState title="No linked questions yet" body="Questions are still being backfilled and linked. This section stays empty rather than guessing which MP asked a question." />}
        </Panel>
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
  const { data, error } = useApi<DocumentDetail>(`/documents/${id}`);
  if (error) return <EmptyState title="Document unavailable" body="The backend could not load this document, so no unsourced substitute is shown." />;
  if (!data) return <LoadingText />;
  return <section><h1 className="section-title">{data.title}</h1><BasicCard title={data.document_type} meta={[data.publication_date, data.committee_name].filter(Boolean).join(" | ")} link={data.source_url} /><Panel title="Mentioned MPs">{data.mentions.length > 0 ? data.mentions.map((item) => <BasicCard key={item.id} title={item.politician.display_name} meta={`${item.match_reason || "match"} | ${item.confidence_score}`} extra={item.snippet} />) : <EmptyState title="No linked MP mentions" body="This document is source-backed, but no MP mention has been confidently linked yet." />}</Panel></section>;
}

function QuestionPage({ id }: { id: string }) {
  const { data, error } = useApi<QuestionDetail>(`/questions/${id}`);
  if (error) return <EmptyState title="Question unavailable" body="The backend could not load this question, so no inferred question record is shown." />;
  if (!data) return <LoadingText />;
  return <section><h1 className="section-title">{data.title}</h1><BasicCard title={data.asked_by_name || "Question asker not linked yet"} meta={[data.department, data.status, data.asked_date || "date not extracted yet"].filter(Boolean).join(" | ")} link={data.source_url} /><Panel title="Question"><p className="rounded border border-line bg-white p-4">{data.question_text || "Question text has not been extracted from the source document yet."}</p></Panel><Panel title="Answer"><p className="rounded border border-line bg-white p-4">{data.answer_text || "Answer text has not been extracted or published in the current source record yet."}</p></Panel></section>;
}

function ListPage<T>({ title, endpoint, render }: { title: string; endpoint: string; render: (item: T) => React.ReactNode }) {
  const { data, loading, error } = useApi<T[]>(`${endpoint}?limit=100`);
  return <section><h1 className="section-title">{title}</h1><ListCoverageNotice title={title} />{loading && <LoadingText />}{error && <EmptyState title={`${title} unavailable`} body="The backend did not return this dataset. Existing source-backed records are not replaced with placeholders." />}{data?.length === 0 && <EmptyState title={`No ${title.toLowerCase()} available yet`} body="This dataset is still being imported or linked. Empty results are shown honestly rather than filled with inferred records." />}<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{data?.map((item, index) => <React.Fragment key={index}>{render(item)}</React.Fragment>)}</div></section>;
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
  return <button onClick={() => navigate(`/politicians/${item.id}`)} className="rounded border border-line bg-white p-4 text-left hover:border-civic"><h2 className="font-semibold">{item.display_name}</h2><p className="text-sm text-slate-700">{confirmedPartyLabel(item.party, item.source_status || "Party not confirmed yet")}</p></button>;
}

function DocumentCard({ item, snippet, navigate }: { item: DocumentRead; snippet?: string; navigate?: (to: string) => void }) {
  return <article className="rounded border border-line bg-white p-4"><button onClick={() => navigate?.(`/documents/${item.id}`)} className="text-left font-semibold hover:text-civic">{item.title}</button><p className="mt-1 text-sm text-slate-700">{[item.document_type, item.publication_date, item.committee_name].filter(Boolean).join(" | ")}</p>{snippet && <p className="mt-2 text-sm">{snippet}</p>}<EvidenceLink href={item.source_url} /></article>;
}

function QuestionCard({ item, navigate }: { item: Question; navigate?: (to: string) => void }) {
  return <article className="rounded border border-line bg-white p-4"><button onClick={() => navigate?.(`/questions/${item.id}`)} className="text-left font-semibold hover:text-civic">{item.title || "Question title not extracted yet"}</button><p className="mt-1 text-sm text-slate-700">{[item.department, item.status, item.asked_date || "date not extracted yet"].filter(Boolean).join(" | ")}</p><EvidenceLink href={item.source_url} /></article>;
}

function BasicCard({ title, meta, link, extra }: { title: string; meta?: string; link?: string; extra?: string }) {
  return <article className="rounded border border-line bg-white p-4"><h2 className="font-semibold">{title}</h2>{meta && <p className="mt-1 text-sm text-slate-700">{meta}</p>}{extra && <p className="mt-2 text-sm">{extra}</p>}<EvidenceLink href={link} /></article>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h2 className="mb-2 text-lg font-semibold">{title}</h2><div className="grid gap-3">{children}</div></section>;
}

function CoverageNotice() {
  return (
    <p className="rounded border border-line bg-white p-4 text-sm text-slate-700">
      Profile sections show only source-backed records linked in production. PMG meetings, attendance, and parliamentary questions are still being backfilled, so missing sections mean "not linked yet", not "no activity".
    </p>
  );
}

function ListCoverageNotice({ title }: { title: string }) {
  if (!["MPs", "Committees", "Parliamentary Questions"].includes(title)) return null;
  return <p className="mb-4 rounded border border-line bg-white p-3 text-sm text-slate-700">This list reflects the records currently imported and linked in production. Coverage is improving as scheduled backfills run.</p>;
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return <div className="rounded border border-line bg-white p-4 text-sm"><p className="font-semibold">{title}</p><p className="mt-1 text-slate-700">{body}</p></div>;
}

function LoadingText() {
  return <p className="text-sm text-slate-600">Loading source-backed data...</p>;
}

function EvidenceLink({ href, label = "Source" }: { href?: string; label?: string }) {
  if (!href) return null;
  return <a href={href} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-civic hover:underline">{label}<ExternalLink size={14} /></a>;
}

function isUnknownParty(party?: Party) {
  return !party || party.name.toLowerCase() === "unknown" || party.short_name.toLowerCase() === "unknown";
}

function confirmedPartyLabel(party?: Party, fallback = "Party not confirmed yet") {
  if (isUnknownParty(party)) return fallback;
  return party?.short_name || party?.name || fallback;
}

function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}${path}`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(response.statusText)))
      .then(setData)
      .catch((err: Error) => {
        setData(null);
        setError(err.message || "Request failed");
      })
      .finally(() => setLoading(false));
  }, [path]);
  return { data, loading, error };
}

createRoot(document.getElementById("root")!).render(<App />);

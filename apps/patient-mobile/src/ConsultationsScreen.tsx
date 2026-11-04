import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import * as Speech from "expo-speech";

type Request = (path: string, init?: RequestInit) => Promise<any>;
type Consultation = {
  id: number; status: string; scheduled_at: string; completed_at?: string | null;
  doctor?: { id: number; name: string } | null;
  recording_consent?: { consented: boolean; consented_at: string; revoked_at?: string | null } | null;
  summary?: { status: string; content: Record<string, { text: string; statement_type: string; source_segment_ids: number[]; sources?: { id: number; start_seconds: number; end_seconds: number }[] }[]> } | null;
  transcript?: { id: number; text: string; language_code?: string | null; start_seconds: number; end_seconds: number; speaker_role?: string | null }[] | null;
};
type ConsentNotice = { version: string; language: string; text: string; fallback?: boolean; preferred_language?: string };

const HEADINGS: Record<string, string> = {
  chief_complaints: "Main concerns", symptoms: "Symptoms", medical_history: "Relevant history",
  doctor_observations: "Doctor observations", medicines_discussed: "Medicines discussed",
  tests_recommended: "Tests recommended", dietary_instructions: "Food and drink",
  dos_and_donts: "What to do and avoid", follow_up_recommendations: "Follow-up", warnings: "Important warnings",
};

export default function ConsultationsScreen({ request }: { request: Request }) {
  const [items, setItems] = useState<Consultation[]>([]);
  const [selected, setSelected] = useState<Consultation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [consentNotice, setConsentNotice] = useState<ConsentNotice | null>(null);
  const [consentError, setConsentError] = useState("");
  async function load() {
    setLoading(true); setError("");
    try { const rows = await request("/consultations") as Consultation[]; setItems(rows); if (selected) setSelected(rows.find((x) => x.id === selected.id) ?? null); }
    catch (e) { setError(e instanceof Error ? e.message : "Consultations could not be loaded."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [request]);
  useEffect(() => {
    if (!selected || selected.status !== "scheduled" || selected.recording_consent?.consented && !selected.recording_consent.revoked_at) { setConsentNotice(null); return; }
    let active = true;
    void request(`/consultations/${selected.id}/consent-info`).then((notice: ConsentNotice) => {
      if (active && notice?.version && notice?.language && notice?.text) setConsentNotice(notice);
      else if (active) setConsentError("The translated recording notice is unavailable. Please contact your care team.");
    }).catch(() => { if (active) setConsentError("The recording notice could not be loaded. Please try again."); });
    return () => { active = false; };
  }, [selected?.id, selected?.status, selected?.recording_consent?.consented, selected?.recording_consent?.revoked_at, request]);
  const card = (title: string, values?: { text: string; statement_type: string; source_segment_ids: number[]; sources?: { id: number; start_seconds: number; end_seconds: number }[] }[]) => values?.length ? <View key={title} style={styles.section}><Text style={styles.heading}>{title}</Text>{values.map((v, i) => <View key={`${title}-${i}`}><Text style={styles.body}>• {v.text}</Text>{!!v.sources?.length && <Text style={styles.source}>From consultation at {v.sources.map(s => `${Math.floor(s.start_seconds / 60)}:${String(Math.floor(s.start_seconds % 60)).padStart(2, "0")}`).join(", ")}</Text>}</View>)}</View> : null;
  if (loading) return <View style={styles.state}><Text style={styles.body}>Loading your consultations…</Text></View>;
  if (error) return <View style={styles.state}><Text accessibilityRole="alert" style={styles.error}>{error}</Text><Action label="Try again" onPress={() => void load()} /></View>;
  async function consent(item: Consultation, agrees: boolean) {
    if (!consentNotice) return;
    try { await request(`/consultations/${item.id}/consent`, { method: "POST", body: JSON.stringify({ consented: agrees, consent_text_version: consentNotice.version, language: consentNotice.language }) }); await load(); setSelected(null); }
    catch (e) { setConsentError(e instanceof Error ? e.message : "Consent could not be recorded."); }
  }
  async function withdrawConsent(item: Consultation) {
    try { await request(`/consultations/${item.id}/consent`, { method: "DELETE" }); await load(); setSelected(null); }
    catch (e) { setConsentError(e instanceof Error ? e.message : "Consent could not be withdrawn."); }
  }
  if (selected) return <View style={styles.stack}>
    <Action label="‹  All consultations" onPress={() => setSelected(null)} />
    <View style={styles.card}><Text style={styles.title}>Consultation with {selected.doctor?.name ?? "your doctor"}</Text><Text style={styles.body}>{new Date(selected.scheduled_at).toLocaleString()}</Text><Text style={styles.badge}>{selected.summary?.status === "approved" ? "Doctor approved" : selected.status.replaceAll("_", " ")}</Text></View>
    {selected.status === "scheduled" && (!selected.recording_consent?.consented || !!selected.recording_consent.revoked_at) && <View style={styles.card}><Text style={styles.heading}>Recording consent</Text>{consentNotice ? <Text accessibilityRole="text" style={styles.body}>{consentNotice.text}</Text> : <Text style={styles.body}>Loading the recording notice in your preferred language…</Text>}{consentNotice?.fallback && <Text accessibilityRole="alert" style={styles.error}>This notice is in English because a translation for your preferred language ({consentNotice.preferred_language}) is not available. Please ask your care team for an interpreter. You can decline recording.</Text>}{!!consentError && <Text accessibilityRole="alert" style={styles.error}>{consentError}</Text>}{consentNotice && !consentNotice.fallback && <Action label="I agree to recording" onPress={() => void consent(selected, true)} />}<Pressable accessibilityRole="button" onPress={() => void consent(selected, false)} style={styles.decline}><Text style={styles.declineText}>I do not agree</Text></Pressable></View>}
    {selected.recording_consent?.consented && !selected.recording_consent.revoked_at && <View style={styles.card}><Text style={styles.heading}>Recording consent given</Text><Text style={styles.body}>Recorded on {new Date(selected.recording_consent.consented_at).toLocaleString()}.</Text><Action label="Withdraw recording consent" onPress={() => void withdrawConsent(selected)} /></View>}
    {selected.summary?.status === "approved" ? <>
      <View style={styles.card}><Text style={styles.heading}>Your consultation summary</Text>{Object.entries(selected.summary.content).map(([key, values]) => card(HEADINGS[key] ?? key, values))}<Action label="Listen to summary" onPress={() => Speech.speak(Object.entries(selected.summary!.content).flatMap(([key, values]) => [HEADINGS[key] ?? key, ...values.map((v) => v.text)]).join(". "), { rate: 0.85 })} /></View>
      {!!selected.transcript?.length && <View style={styles.card}><Text style={styles.heading}>Consultation transcript</Text>{selected.transcript.map((part) => <Text key={part.id} style={styles.transcript}>{Math.floor(part.start_seconds / 60)}:{String(Math.floor(part.start_seconds % 60)).padStart(2, "0")}  {part.speaker_role ?? "Speaker"}: {part.text}</Text>)}</View>}
    </> : <View style={styles.card}><Text style={styles.body}>Your doctor has not approved a summary yet. It will appear here after review.</Text></View>}
  </View>;
  if (!items.length) return <View style={styles.state}><Text style={styles.title}>No consultations yet</Text><Text style={styles.body}>Consultations shared by your care team will appear here.</Text></View>;
  return <View style={styles.stack}>{items.map((item) => <Pressable accessibilityRole="button" key={item.id} onPress={() => setSelected(item)} style={styles.card}>
    <Text style={styles.title}>{item.doctor?.name ?? "Consultation"}</Text><Text style={styles.body}>{new Date(item.scheduled_at).toLocaleString()}</Text><Text style={styles.badge}>{item.summary?.status === "approved" ? "Doctor approved summary" : item.status.replaceAll("_", " ")}</Text><Text style={styles.link}>Open consultation  ›</Text>
  </Pressable>)}</View>;
}

function Action({ label, onPress }: { label: string; onPress: () => void }) { return <Pressable accessibilityRole="button" onPress={onPress} style={styles.action}><Text style={styles.actionText}>{label}</Text></Pressable>; }

const styles = StyleSheet.create({ stack: { gap: 14 }, state: { minHeight: 220, alignItems: "center", justifyContent: "center", padding: 24, backgroundColor: "#fff", borderRadius: 18, gap: 12 }, card: { backgroundColor: "#fff", borderColor: "#d8e4e1", borderWidth: 1, borderRadius: 18, padding: 18, gap: 7 }, title: { color: "#173b38", fontSize: 22, fontWeight: "800" }, heading: { color: "#173b38", fontSize: 19, fontWeight: "800", marginTop: 8 }, body: { color: "#425c58", fontSize: 17, lineHeight: 25 }, section: { marginTop: 5, gap: 4 }, source: { color: "#526b67", fontSize: 14, marginLeft: 14, marginTop: 2 }, badge: { alignSelf: "flex-start", color: "#075e58", backgroundColor: "#e4f3f0", fontSize: 14, fontWeight: "800", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, textTransform: "capitalize" }, action: { minHeight: 50, justifyContent: "center", backgroundColor: "#075e58", borderRadius: 12, paddingHorizontal: 16, marginTop: 8 }, actionText: { color: "#fff", fontSize: 17, fontWeight: "800", textAlign: "center" }, decline: { minHeight: 46, justifyContent: "center", alignItems: "center" }, declineText: { color: "#075e58", textDecorationLine: "underline", fontSize: 16, fontWeight: "700" }, link: { color: "#075e58", fontSize: 16, fontWeight: "800", marginTop: 5 }, transcript: { color: "#354e4b", fontSize: 16, lineHeight: 24, paddingVertical: 5, borderTopWidth: 1, borderTopColor: "#e5edeb" }, error: { color: "#8e2c25", fontSize: 17, lineHeight: 25, textAlign: "center" } });

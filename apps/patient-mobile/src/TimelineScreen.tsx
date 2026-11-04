import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import * as Speech from "expo-speech";

export type TimelineEvent = {
  id: number;
  event_type: string;
  title: string;
  description?: string | null;
  event_date: string;
  source_module: string;
  status: string;
  metadata?: Record<string, unknown>;
};

export type NextStep = {
  event_id: number;
  event_type: string;
  title: string;
  description?: string | null;
  event_date: string;
  action: string;
  status: string;
};

export type TimelineSummary = {
  total_events: number;
  upcoming_count: number;
  pending_count: number;
  completed_count: number;
  next_steps: NextStep[];
};

type Requester = (path: string, init?: RequestInit) => Promise<unknown>;
type ViewFilter = "all" | "upcoming" | "completed" | "pending";

const VIEW_FILTERS: { id: ViewFilter; label: string }[] = [
  { id: "all", label: "All history" },
  { id: "upcoming", label: "Upcoming" },
  { id: "completed", label: "Completed" },
  { id: "pending", label: "Pending" },
];
const CATEGORIES = [
  { label: "All", types: [] as string[] },
  { label: "Consultations", types: ["consultation_scheduled", "consultation_completed", "summary_generated", "summary_approved"] },
  { label: "Medicines", types: ["prescription_uploaded", "prescription_approved", "medication_schedule_activated", "prescription_updated", "medication_course_completed", "medication_started", "medication_completed", "medication_schedule_changed", "refill_required"] },
  { label: "Laboratory tests", types: ["test_recommended", "test_scheduled", "test_completed"] },
  { label: "Reports", types: ["report_uploaded", "report_reviewed"] },
  { label: "Appointments", types: ["follow_up_scheduled", "appointment_updated", "appointment_completed", "appointment_cancelled"] },
];
const COMPLETE = ["completed", "approved", "reviewed", "cancelled", "rejected"];
const PENDING = ["scheduled", "pending", "recommended", "pending_review", "active", "in_progress"];

export default function TimelineScreen({ request }: { request: Requester }) {
  const [view, setView] = useState<ViewFilter>("all");
  const [category, setCategory] = useState("All");
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<TimelineEvent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const categoryTypes = useMemo(() => CATEGORIES.find((item) => item.label === category)?.types ?? [], [category]);
  const load = useCallback(async (nextPage = 1) => {
    setError("");
    if (nextPage === 1) setLoading(true); else setLoadingMore(true);
    try {
      const params = new URLSearchParams({ page: String(nextPage), page_size: "25" });
      categoryTypes.forEach((type) => params.append("event_type", type));
      (view === "completed" ? COMPLETE : view === "pending" ? PENDING : []).forEach((status) => params.append("status", status));
      const route = view === "upcoming" ? "/timeline/upcoming" : "/timeline";
      const result = await request(`${route}?${params.toString()}`) as { items: TimelineEvent[]; total: number };
      const nextEvents = result.items ?? [];
      setEvents((current) => nextPage === 1 ? nextEvents : [...current, ...nextEvents]);
      setTotal(result.total ?? nextEvents.length);
      setPage(nextPage);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Timeline could not be loaded.");
    } finally { setLoading(false); setLoadingMore(false); }
  }, [categoryTypes, request, view]);

  useEffect(() => { void load(); }, [load]);

  async function openDetail(event: TimelineEvent) {
    if (selected?.id === event.id) { setSelected(null); return; }
    setSelected(event);
    setDetailLoading(true);
    setDetailError("");
    try { setSelected(await request(`/timeline/${event.id}`) as TimelineEvent); }
    catch (reason) { setDetailError(reason instanceof Error ? reason.message : "Event details could not be loaded."); }
    finally { setDetailLoading(false); }
  }

  function chooseView(value: ViewFilter) { setSelected(null); setView(value); }
  function chooseCategory(value: string) { setSelected(null); setCategory(value); }
  function readTimeline() {
    const spoken = events.length
      ? events.map((event) => `${event.title}. ${formatDate(event.event_date)}. Status: ${formatStatus(event.status)}.${event.description ? ` ${event.description}` : ""}`).join(" ")
      : "There are no healthcare timeline events recorded yet.";
    Speech.speak(`Your healthcare timeline. ${spoken}`, { rate: 0.88 });
  }

  return <View style={styles.wrap}>
    <View style={styles.intro}><Text style={styles.introTitle}>Your healthcare journey</Text><Text style={styles.introText}>A clear history of activities recorded by your care team.</Text></View>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll} contentContainerStyle={styles.filterRow} accessibilityRole="tablist">
      {VIEW_FILTERS.map((item) => <Pressable key={item.id} accessibilityRole="tab" accessibilityState={{ selected: view === item.id }} onPress={() => chooseView(item.id)} style={[styles.viewFilter, view === item.id && styles.selectedViewFilter]}><Text style={[styles.viewFilterText, view === item.id && styles.selectedViewText]}>{item.label}</Text></Pressable>)}
    </ScrollView>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll} contentContainerStyle={styles.categoryRow}>
      {CATEGORIES.map((item) => <Pressable key={item.label} accessibilityRole="button" accessibilityState={{ selected: category === item.label }} onPress={() => chooseCategory(item.label)} style={[styles.categoryFilter, category === item.label && styles.selectedCategory]}><Text style={[styles.categoryText, category === item.label && styles.selectedCategoryText]}>{item.label}</Text></Pressable>)}
    </ScrollView>
    <Pressable accessibilityRole="button" onPress={readTimeline} style={styles.readButton}><Text style={styles.readButtonText}>◖))  Read timeline aloud</Text></Pressable>
    {!!error && <View style={styles.errorBox}><Text accessibilityRole="alert" style={styles.errorText}>{error}</Text><Pressable onPress={() => void load()} style={styles.retry}><Text style={styles.retryText}>Try again</Text></Pressable></View>}
    {loading ? <View style={styles.stateBox}><ActivityIndicator size="large" color="#08716b" /><Text style={styles.stateText}>Loading your healthcare history…</Text></View> : events.length === 0 ? <View style={styles.emptyBox}><Text style={styles.emptyIcon}>◷</Text><Text style={styles.emptyTitle}>{error ? "Timeline unavailable" : "No timeline events yet"}</Text><Text style={styles.emptyText}>{error ? "Check your connection and try again." : "When your care team records appointments, tests, or treatment updates, they will appear here."}</Text></View> : <View style={styles.timelineList}>
      <View style={styles.timelineRail} />
      {events.map((event, index) => <View key={event.id} style={styles.eventRow}>
        <View style={styles.eventMarker}><Text style={styles.eventMarkerText}>{eventIcon(event)}</Text></View>
        <Pressable accessibilityRole="button" accessibilityLabel={`${event.title}, ${formatDate(event.event_date)}, ${event.status}. Show details`} onPress={() => void openDetail(event)} style={styles.eventCard}>
          <View style={styles.eventTop}><Text style={styles.eventCategory}>{categoryLabel(event)}</Text><Text style={styles.eventDate}>{formatDate(event.event_date)}</Text></View>
          <Text style={styles.eventTitle}>{event.title}</Text>
          {!!event.description && <Text numberOfLines={2} style={styles.eventDescription}>{event.description}</Text>}
          <View style={styles.eventBottom}><Text style={styles.statusBadge}>{formatStatus(event.status)}</Text><Text style={styles.detailsLink}>{selected?.id === event.id ? "Hide details" : "Details  ›"}</Text></View>
          {selected?.id === event.id && <View style={styles.detailBox}>
            {detailLoading ? <View style={styles.detailLoading}><ActivityIndicator color="#08716b" /><Text style={styles.eventDescription}>Loading event details…</Text></View> : detailError ? <Text accessibilityRole="alert" style={styles.errorText}>{detailError}</Text> : <><Text style={styles.detailHeading}>Event details</Text><Text style={styles.eventDescription}>{selected.description || "No additional details were recorded."}</Text><Text style={styles.detailMeta}>Recorded by {selected.source_module.replace(/_/g, " ")}</Text></>}
          </View>}
        </Pressable>
        {index < events.length - 1 && <View style={styles.eventSpacer} />}
      </View>)}
    </View>}
    {!loading && events.length < total && <Pressable accessibilityRole="button" disabled={loadingMore} onPress={() => void load(page + 1)} style={styles.loadMore}><Text style={styles.loadMoreText}>{loadingMore ? "Loading…" : "Load more events"}</Text></Pressable>}
    <Text style={styles.disclaimer}>Timeline entries reference records from your care team. They do not replace advice from your doctor.</Text>
  </View>;
}

export function NextStepsCard({ steps, loading, onOpenTimeline }: { steps: NextStep[]; loading: boolean; onOpenTimeline: () => void }) {
  return <View style={styles.nextCard}>
    <View style={styles.nextHeader}><View><Text style={styles.nextKicker}>FROM YOUR CARE RECORDS</Text><Text style={styles.nextTitle}>Your Next Steps</Text></View><Text style={styles.nextIcon}>✓</Text></View>
    {loading ? <View style={styles.nextLoading}><ActivityIndicator color="#08716b" /><Text style={styles.nextEmpty}>Loading your recorded next steps…</Text></View> : steps.length === 0 ? <Text style={styles.nextEmpty}>There are no pending activities recorded for you.</Text> : steps.map((step) => <View key={step.event_id} style={styles.nextStep}><Text style={styles.nextBullet}>•</Text><View style={styles.nextCopy}><Text style={styles.nextAction}>{step.action}</Text><Text style={styles.nextDate}>{step.title} · {formatDate(step.event_date)}</Text></View></View>)}
    <Pressable accessibilityRole="button" onPress={onOpenTimeline} style={styles.nextLink}><Text style={styles.nextLinkText}>Open healthcare timeline  ›</Text></Pressable>
  </View>;
}

export function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function eventIcon(event: TimelineEvent) {
  if (event.source_module === "consultation" || event.event_type.startsWith("consultation_") || event.event_type.startsWith("summary_")) return "⚕";
  if (event.source_module === "medicine" || event.source_module === "prescription") return "+";
  if (event.source_module === "laboratory") return event.event_type.startsWith("report_") ? "▤" : "◉";
  return "▦";
}

function categoryLabel(event: TimelineEvent) {
  if (event.source_module === "consultation") return "CONSULTATION";
  if (event.source_module === "medicine" || event.source_module === "prescription") return "MEDICINES";
  if (event.source_module === "laboratory") return event.event_type.startsWith("report_") ? "LABORATORY REPORT" : "LABORATORY TEST";
  return "APPOINTMENT";
}

function formatStatus(value: string) { return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }

const styles = StyleSheet.create({
  wrap: { gap: 13 },
  intro: { backgroundColor: "#e3f2ef", borderRadius: 18, padding: 18 },
  introTitle: { color: "#153e3a", fontSize: 22, fontWeight: "800" },
  introText: { color: "#355a56", fontSize: 16, lineHeight: 24, marginTop: 5 },
  filterScroll: { flexGrow: 0, maxHeight: 54 },
  filterRow: { alignItems: "center", gap: 8, paddingRight: 5 },
  viewFilter: { minHeight: 46, paddingHorizontal: 15, borderRadius: 12, justifyContent: "center", borderWidth: 1, borderColor: "#b5cbc6", backgroundColor: "#fff" },
  selectedViewFilter: { backgroundColor: "#075e58", borderColor: "#075e58" },
  viewFilterText: { color: "#31524d", fontSize: 15, fontWeight: "700" },
  selectedViewText: { color: "#fff" },
  categoryRow: { alignItems: "center", gap: 7 },
  categoryFilter: { minHeight: 42, borderRadius: 21, borderWidth: 1, borderColor: "#b5cbc6", paddingHorizontal: 14, alignItems: "center", justifyContent: "center", backgroundColor: "#fff" },
  selectedCategory: { backgroundColor: "#e4f3f0", borderColor: "#57938a" },
  categoryText: { color: "#45615d", fontSize: 14, fontWeight: "700" },
  selectedCategoryText: { color: "#075e58" },
  readButton: { minHeight: 48, alignSelf: "flex-start", justifyContent: "center", paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: "#92b9b1", backgroundColor: "#fff" },
  readButtonText: { color: "#075e58", fontSize: 15, fontWeight: "800" },
  stateBox: { minHeight: 200, justifyContent: "center", alignItems: "center", gap: 13, backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#d8e4e1" },
  stateText: { color: "#45615d", fontSize: 16 },
  emptyBox: { minHeight: 250, justifyContent: "center", alignItems: "center", padding: 24, backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#d8e4e1" },
  emptyIcon: { color: "#08716b", fontSize: 43, fontWeight: "800" },
  emptyTitle: { color: "#193d39", fontSize: 21, fontWeight: "800", textAlign: "center", marginTop: 10 },
  emptyText: { color: "#516864", fontSize: 16, lineHeight: 24, textAlign: "center", maxWidth: 500, marginTop: 7 },
  timelineList: { position: "relative", gap: 0, paddingTop: 4 },
  timelineRail: { position: "absolute", top: 25, bottom: 26, left: 21, width: 3, backgroundColor: "#cfe4df", borderRadius: 2 },
  eventRow: { position: "relative", paddingLeft: 53 },
  eventMarker: { position: "absolute", left: 0, top: 18, width: 45, height: 45, borderRadius: 15, borderWidth: 3, borderColor: "#f5f8f7", backgroundColor: "#dcedea", alignItems: "center", justifyContent: "center", zIndex: 1 },
  eventMarkerText: { color: "#08716b", fontSize: 21, fontWeight: "800" },
  eventCard: { backgroundColor: "#fff", borderRadius: 17, borderWidth: 1, borderColor: "#d8e4e1", padding: 16, marginTop: 8 },
  eventTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  eventCategory: { color: "#08716b", fontSize: 12, fontWeight: "800", letterSpacing: 1 },
  eventDate: { color: "#607773", fontSize: 13, fontWeight: "600" },
  eventTitle: { color: "#193d39", fontSize: 19, fontWeight: "800", lineHeight: 25, marginTop: 9 },
  eventDescription: { color: "#516864", fontSize: 16, lineHeight: 24, marginTop: 6 },
  eventBottom: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 9 },
  statusBadge: { color: "#315d57", fontSize: 13, fontWeight: "700", backgroundColor: "#edf5f3", borderRadius: 16, paddingVertical: 6, paddingHorizontal: 10, overflow: "hidden" },
  detailsLink: { color: "#075e58", fontSize: 15, fontWeight: "800" },
  detailBox: { borderTopWidth: 1, borderTopColor: "#e5edeb", marginTop: 13, paddingTop: 12 },
  detailHeading: { color: "#193d39", fontSize: 16, fontWeight: "800" },
  detailMeta: { color: "#667d79", fontSize: 13, marginTop: 8 },
  detailLoading: { flexDirection: "row", alignItems: "center", gap: 10 },
  eventSpacer: { height: 10 },
  loadMore: { minHeight: 52, borderRadius: 13, borderWidth: 1, borderColor: "#8fb4ad", alignItems: "center", justifyContent: "center", backgroundColor: "#fff" },
  loadMoreText: { color: "#075e58", fontSize: 16, fontWeight: "800" },
  disclaimer: { color: "#667d79", fontSize: 14, lineHeight: 20, marginTop: 3 },
  errorBox: { backgroundColor: "#fff2ef", borderRadius: 12, padding: 13, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  errorText: { color: "#853b34", fontSize: 15, lineHeight: 21, flex: 1 },
  retry: { minHeight: 40, paddingHorizontal: 10, alignItems: "center", justifyContent: "center" },
  retryText: { color: "#853b34", fontSize: 15, fontWeight: "800" },
  nextCard: { backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#b7d8d1", padding: 18, gap: 11 },
  nextHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  nextKicker: { color: "#08716b", fontSize: 12, fontWeight: "800", letterSpacing: 1.2 },
  nextTitle: { color: "#193d39", fontSize: 22, fontWeight: "800", marginTop: 3 },
  nextIcon: { color: "#08716b", backgroundColor: "#e3f2ef", overflow: "hidden", borderRadius: 14, paddingHorizontal: 10, paddingVertical: 4, fontSize: 23, fontWeight: "800" },
  nextEmpty: { color: "#516864", fontSize: 15, lineHeight: 22 },
  nextLoading: { flexDirection: "row", alignItems: "center", gap: 10 },
  nextStep: { flexDirection: "row", gap: 9, alignItems: "flex-start", paddingTop: 9, borderTopWidth: 1, borderTopColor: "#e6efed" },
  nextBullet: { color: "#08716b", fontSize: 23, lineHeight: 24 },
  nextCopy: { flex: 1 },
  nextAction: { color: "#244641", fontSize: 16, fontWeight: "700", lineHeight: 23 },
  nextDate: { color: "#687f7b", fontSize: 14, lineHeight: 20, marginTop: 2 },
  nextLink: { minHeight: 42, justifyContent: "center", alignSelf: "flex-start" },
  nextLinkText: { color: "#075e58", fontSize: 15, fontWeight: "800" },
});

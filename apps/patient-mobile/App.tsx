import { useCallback, useEffect, useMemo, useState } from "react";
import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import TimelineScreen, { NextStepsCard, type TimelineSummary } from "./src/TimelineScreen";
import ConsultationsScreen from "./src/ConsultationsScreen";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from "react-native";

const API = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const ACCESS_KEY = "auth.access";
const REFRESH_KEY = "auth.refresh";

type PatientProfile = {
  id: number;
  name: string;
  email: string;
  date_of_birth?: string | null;
  phone?: string | null;
  preferred_language?: string | null;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  medical_history?: string | null;
  allergies?: string | null;
};

const NAV = [
  { id: "home", icon: "⌂", label: "Home" },
  { id: "timeline", icon: "◷", label: "Healthcare Timeline" },
  { id: "medicines", icon: "+", label: "Medicines" },
  { id: "consultations", icon: "▤", label: "Consultations" },
  { id: "appointments", icon: "▦", label: "Appointments" },
  { id: "laboratory", icon: "◉", label: "Laboratory Reports" },
  { id: "assistant", icon: "◌", label: "AI Assistant" },
  { id: "history", icon: "♡", label: "Medical History" },
  { id: "family", icon: "♧", label: "Family" },
  { id: "settings", icon: "⚙", label: "Settings" },
] as const;

type ScreenId = (typeof NAV)[number]["id"];
const EMPTY_TIMELINE_SUMMARY: TimelineSummary = { total_events: 0, upcoming_count: 0, pending_count: 0, completed_count: 0, next_steps: [] };

async function storeTokens(data: { access_token: string; refresh_token?: string }) {
  await SecureStore.setItemAsync(ACCESS_KEY, data.access_token);
  if (data.refresh_token) await SecureStore.setItemAsync(REFRESH_KEY, data.refresh_token);
}

async function clearTokens() {
  await SecureStore.deleteItemAsync(ACCESS_KEY);
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}

export default function App() {
  const { width } = useWindowDimensions();
  const wide = width >= 850;
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [screen, setScreen] = useState<ScreenId>("home");
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [profileDraft, setProfileDraft] = useState<Partial<PatientProfile>>({});
  const [timelineSummary, setTimelineSummary] = useState<TimelineSummary>(EMPTY_TIMELINE_SUMMARY);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    let token = await SecureStore.getItemAsync(ACCESS_KEY);
    const send = (value: string | null) => fetch(`${API}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}), ...(value ? { Authorization: `Bearer ${value}` } : {}) },
    });
    let response = await send(token);
    if (response.status === 401 && path !== "/auth/refresh") {
      const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
      if (!refresh) throw new Error("Your session has ended. Please sign in again.");
      const rotated = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!rotated.ok) {
        await clearTokens();
        setAccessToken("");
        throw new Error("Your session has ended. Please sign in again.");
      }
      const tokens = await rotated.json();
      await storeTokens(tokens);
      token = tokens.access_token;
      setAccessToken(tokens.access_token);
      response = await send(token);
    }
    const result = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(result?.detail ?? result?.error?.message ?? "We could not complete that request. Please try again.");
    return result;
  }, []);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const data = await request("/patients/me") as PatientProfile;
      setProfile(data);
      setProfileDraft(data);
      return data;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We could not load your profile.");
      return null;
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    if (!accessToken || screen !== "home") return;
    let active = true;
    setSummaryLoading(true);
    request("/timeline/summary").then((value) => {
      if (active && value && typeof value === "object") setTimelineSummary({ ...EMPTY_TIMELINE_SUMMARY, ...(value as TimelineSummary) });
    }).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : "Your next steps could not be loaded.");
    }).finally(() => { if (active) setSummaryLoading(false); });
    return () => { active = false; };
  }, [accessToken, request, screen]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const access = await SecureStore.getItemAsync(ACCESS_KEY);
      const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
      if (!mounted) return;
      if (access) {
        setAccessToken(access);
        await loadProfile();
      } else if (refresh) {
        try {
          const response = await fetch(`${API}/auth/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }) });
          if (!response.ok) throw new Error("Session expired");
          const tokens = await response.json();
          await storeTokens(tokens);
          if (mounted) { setAccessToken(tokens.access_token); await loadProfile(); }
        } catch {
          await clearTokens();
        }
      }
    })();
    return () => { mounted = false; };
  }, [loadProfile]);

  async function submitAuth() {
    setLoading(true);
    setMessage("");
    try {
      if (registering) {
        await request("/auth/register/patient", { method: "POST", body: JSON.stringify({ email, name, password, role: "patient" }) });
        setRegistering(false);
        setMessage("Your account is ready. Sign in to continue.");
      } else {
        const data = await request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
        if (data.user?.role !== "patient") throw new Error("Please use a patient account to sign in here.");
        await storeTokens(data);
        setAccessToken(data.access_token);
        await loadProfile();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We could not sign you in.");
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
    try {
      await request("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: refresh }) });
    } catch {
      // Clear local credentials even if the network is unavailable; the server session expires or can be revoked separately.
    }
    await clearTokens();
    setAccessToken("");
    setProfile(null);
    setScreen("home");
    setMessage("You are signed out.");
  }

  async function saveProfile() {
    setSaving(true);
    try {
      const data = await request("/patients/me", { method: "PATCH", body: JSON.stringify({
        name: profileDraft.name,
        date_of_birth: profileDraft.date_of_birth || null,
        phone: profileDraft.phone || null,
        preferred_language: profileDraft.preferred_language || "en",
        emergency_contact_name: profileDraft.emergency_contact_name || null,
        emergency_contact_phone: profileDraft.emergency_contact_phone || null,
        medical_history: profileDraft.medical_history || null,
        allergies: profileDraft.allergies || null,
      }) }) as PatientProfile;
      setProfile(data);
      setProfileDraft(data);
      setMessage("Your information has been saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We could not save your information.");
    } finally { setSaving(false); }
  }

  function readAloud() {
    const namePart = profile?.name ? `, ${profile.name.split(" ")[0]}` : "";
    const text = screen === "history"
      ? `Medical history. Known allergies: ${profile?.allergies || "none recorded"}. Medical history: ${profile?.medical_history || "none recorded"}. Emergency contact: ${profile?.emergency_contact_name || "none recorded"}.`
      : screen === "settings"
        ? `Settings. Your name is ${profile?.name || "not recorded"}. Preferred language: ${profile?.preferred_language || "not set"}. Use the form to update your profile.`
        : screen === "home"
          ? `Welcome${namePart}. Your health information is in one place. Your next steps: ${timelineSummary.next_steps.length ? timelineSummary.next_steps.map((step) => step.action).join(" ") : "There are no pending healthcare activities recorded."}`
          : `Welcome${namePart}. You are viewing ${NAV.find((item) => item.id === screen)?.label ?? "Home"}. Use the timeline read aloud button to hear your recorded activities.`;
    Speech.speak(text, { language: profile?.preferred_language || undefined, rate: 0.88 });
  }

  const title = useMemo(() => NAV.find((item) => item.id === screen)?.label ?? "Home", [screen]);
  const updateDraft = (field: keyof PatientProfile, value: string) => setProfileDraft((old) => ({ ...old, [field]: value }));

  if (!accessToken) return (
    <SafeAreaView style={styles.authPage}>
      <ScrollView contentContainerStyle={styles.authContent}>
        <Text style={styles.brand}>PERSONAL HEALTHCARE COMPANION</Text>
        <View style={styles.authCard}>
          <Text style={styles.authIcon}>♡</Text>
          <Text style={styles.authTitle}>{registering ? "Create your account" : "Welcome"}</Text>
          <Text style={styles.authLead}>Your health information, in one easy place.</Text>
          {registering && <TextInput accessibilityLabel="Full name" style={styles.input} placeholder="Full name" value={name} onChangeText={setName} autoCapitalize="words" />}
          <TextInput accessibilityLabel="Email address" style={styles.input} placeholder="Email address" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" />
          <TextInput accessibilityLabel="Password" style={styles.input} placeholder="Password" value={password} onChangeText={setPassword} secureTextEntry />
          <Button label={loading ? "Please wait…" : registering ? "Create account" : "Sign in"} onPress={submitAuth} disabled={loading} />
          <Pressable accessibilityRole="button" style={styles.authSwitch} onPress={() => { setRegistering(!registering); setMessage(""); }}>
            <Text style={styles.authSwitchText}>{registering ? "Already have an account? Sign in" : "New here? Create an account"}</Text>
          </Pressable>
          {!!message && <Text accessibilityLiveRegion="polite" style={styles.feedback}>{message}</Text>}
        </View>
        <Text style={styles.privacyNote}>Your account information is protected. For urgent medical help, contact your local emergency service.</Text>
      </ScrollView>
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={styles.page}>
      <View style={styles.topbar}>
        <View style={styles.brandMark}><Text style={styles.brandMarkText}>+</Text></View>
        <View style={styles.topTitleWrap}><Text style={styles.topBrand}>MY HEALTH</Text><Text style={styles.topSubtitle}>{profile?.name ? `Hello, ${profile.name}` : "Your care, all together"}</Text></View>
        <Pressable accessibilityRole="button" accessibilityLabel="Read this page aloud" style={styles.readButton} onPress={readAloud}><Text style={styles.readIcon}>◖))</Text><Text style={styles.readText}>Read aloud</Text></Pressable>
      </View>
      <View style={[styles.layout, wide && styles.layoutWide]}>
        {wide && <ScrollView style={styles.sidebar} contentContainerStyle={styles.sidebarContent}>
          <Text style={styles.navHeading}>YOUR CARE</Text>
          {NAV.map((item) => <NavButton key={item.id} item={item} active={screen === item.id} onPress={() => { setScreen(item.id); setMessage(""); if (item.id === "history" || item.id === "settings") void loadProfile(); }} compact />)}
          <Pressable accessibilityRole="button" onPress={logout} style={styles.signOut}><Text style={styles.signOutText}>↪  Sign out</Text></Pressable>
        </ScrollView>}
        <ScrollView style={styles.mainScroll} contentContainerStyle={styles.mainContent}>
          <View style={styles.pageHeading}><View><Text style={styles.eyebrow}>{screen === "home" ? "YOUR HEALTH AT A GLANCE" : "YOUR CARE"}</Text><Text accessibilityRole="header" style={styles.pageTitle}>{title}</Text></View>
            {!wide && <Pressable accessibilityRole="button" accessibilityLabel="Sign out" onPress={logout} style={styles.mobileLogout}><Text style={styles.mobileLogoutText}>Sign out</Text></Pressable>}
          </View>
          {loading && <View style={styles.loading}><ActivityIndicator color="#08716b" size="large" /><Text style={styles.loadingText}>Loading your information…</Text></View>}
          {!loading && screen === "home" && <HomeScreen profile={profile} timelineSummary={timelineSummary} summaryLoading={summaryLoading} onNavigate={setScreen} onRead={readAloud} />}
          {!loading && screen === "timeline" && <TimelineScreen request={request} />}
          {!loading && screen === "medicines" && <UnavailableCard icon="+" title="Medicine schedule" description="There are no medicine records to show yet. Medicine scheduling will appear here when connected to your care team." />}
          {!loading && screen === "consultations" && <ConsultationsScreen request={request} />}
          {!loading && screen === "appointments" && <UnavailableCard icon="▦" title="Appointments" description="You do not have appointment details available here yet." />}
          {!loading && screen === "laboratory" && <UnavailableCard icon="◉" title="Laboratory reports" description="Test orders and reports will appear here when your care team shares them with you." />}
          {!loading && screen === "assistant" && <UnavailableCard icon="◌" title="AI assistant" description="The assistant is not available yet. You can still review your health information and contact your care team." />}
          {!loading && screen === "history" && <MedicalHistory profile={profile} onRead={readAloud} />}
          {!loading && screen === "family" && <UnavailableCard icon="♧" title="Family and caregivers" description="Caregiver access is managed by patient consent. Caregiver management is not yet available in this app." />}
          {!loading && screen === "settings" && <SettingsScreen profile={profile} draft={profileDraft} update={updateDraft} save={saveProfile} saving={saving} />}
          {!!message && <Text accessibilityLiveRegion="polite" style={styles.feedback}>{message}</Text>}
          <Text style={styles.footer}>If you need urgent care, contact your local emergency service.</Text>
        </ScrollView>
      </View>
      {!wide && <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bottomNav} contentContainerStyle={styles.bottomNavContent}>
        {NAV.map((item) => <NavButton key={item.id} item={item} active={screen === item.id} onPress={() => { setScreen(item.id); setMessage(""); if (item.id === "history" || item.id === "settings") void loadProfile(); }} />)}
      </ScrollView>}
    </SafeAreaView>
  );
}

function Button({ label, onPress, disabled = false, secondary = false }: { label: string; onPress: () => void; disabled?: boolean; secondary?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.primaryButton, secondary && styles.secondaryButton, disabled && styles.disabledButton]}><Text style={[styles.primaryButtonText, secondary && styles.secondaryButtonText]}>{label}</Text></Pressable>;
}

function NavButton({ item, active, onPress, compact = false }: { item: (typeof NAV)[number]; active: boolean; onPress: () => void; compact?: boolean }) {
  return <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} onPress={onPress} style={[compact ? styles.sideNavItem : styles.tabItem, active && (compact ? styles.sideNavActive : styles.tabActive)]}>
    <Text style={[compact ? styles.sideIcon : styles.tabIcon, active && styles.activeIcon]}>{item.icon}</Text>
    <Text numberOfLines={2} style={[compact ? styles.sideLabel : styles.tabLabel, active && styles.activeLabel]}>{item.label}</Text>
  </Pressable>;
}

function HomeScreen({ profile, timelineSummary, summaryLoading, onNavigate, onRead }: { profile: PatientProfile | null; timelineSummary: TimelineSummary; summaryLoading: boolean; onNavigate: (screen: ScreenId) => void; onRead: () => void }) {
  return <View style={styles.stack}>
    <View style={styles.welcomeCard}>
      <View style={styles.welcomeCopy}><Text style={styles.welcomeEyebrow}>GOOD TO SEE YOU</Text><Text style={styles.welcomeTitle}>Hello{profile?.name ? `, ${profile.name.split(" ")[0]}` : ""}.</Text><Text style={styles.welcomeSub}>Here is your health information in one place.</Text></View>
      <Text style={styles.welcomeArt}>♡</Text>
    </View>
    <Pressable accessibilityRole="button" accessibilityLabel="Open AI assistant. Not available yet" style={styles.assistantCard} onPress={() => onNavigate("assistant")}>
      <View style={styles.assistantIcon}><Text style={styles.assistantIconText}>◌</Text></View><View style={styles.assistantCopy}><Text style={styles.assistantTitle}>Need help?</Text><Text style={styles.assistantDescription}>Assistant access will be available in a later update.</Text></View><Text style={styles.assistantArrow}>›</Text>
    </Pressable>
    <View style={styles.sectionHeading}><Text style={styles.sectionTitle}>Your care today</Text><Text style={styles.sectionHint}>Current information from your account</Text></View>
    <View style={styles.cardGrid}>
      <InfoCard icon="+" title="Today's medicines" text="No medicine schedule is available yet." action="View medicines" onPress={() => onNavigate("medicines")} />
      <InfoCard icon="▦" title="Next appointment" text="No upcoming appointment details are available." action="View appointments" onPress={() => onNavigate("appointments")} />
      <InfoCard icon="◉" title="Laboratory tests" text="No pending laboratory tests are available." action="View reports" onPress={() => onNavigate("laboratory")} />
      <InfoCard icon="♡" title="Doctor instructions" text="There are no shared instructions to show." action="View consultations" onPress={() => onNavigate("consultations")} />
    </View>
    <View style={styles.summaryCard}>
      <View style={styles.summaryHead}><Text style={styles.sectionTitle}>Recent consultation</Text><Text style={styles.summaryIcon}>▤</Text></View>
      <Text style={styles.cardBody}>Your consultation summaries will appear here after your care team shares them.</Text>
      <Pressable accessibilityRole="button" style={styles.textAction} onPress={() => onNavigate("consultations")}><Text style={styles.textActionText}>View consultation history  ›</Text></Pressable>
    </View>
    <View style={styles.summaryCard}>
      <View style={styles.summaryHead}><Text style={styles.sectionTitle}>Coming up</Text><Text style={styles.summaryIcon}>◷</Text></View>
      <Text style={styles.cardBody}>{summaryLoading ? "Checking your upcoming activities…" : timelineSummary.upcoming_count === 0 ? "No upcoming healthcare activities are recorded." : `${timelineSummary.upcoming_count} upcoming healthcare ${timelineSummary.upcoming_count === 1 ? "activity" : "activities"} recorded.`}</Text>
      <Pressable accessibilityRole="button" style={styles.textAction} onPress={() => onNavigate("timeline")}><Text style={styles.textActionText}>Open healthcare timeline  ›</Text></Pressable>
    </View>
    <NextStepsCard steps={timelineSummary.next_steps} loading={summaryLoading} onOpenTimeline={() => onNavigate("timeline")} />
    <Button label="Read my dashboard aloud" secondary onPress={onRead} />
  </View>;
}

function InfoCard({ icon, title, text, action, onPress }: { icon: string; title: string; text: string; action: string; onPress: () => void }) {
  return <View style={styles.infoCard}><View style={styles.infoIcon}><Text style={styles.infoIconText}>{icon}</Text></View><Text style={styles.infoTitle}>{title}</Text><Text style={styles.cardBody}>{text}</Text><Pressable accessibilityRole="button" onPress={onPress} style={styles.textAction}><Text style={styles.textActionText}>{action}  ›</Text></Pressable></View>;
}

function UnavailableCard({ icon, title, description }: { icon: string; title: string; description: string }) {
  return <View style={styles.emptyCard}><View style={styles.emptyIcon}><Text style={styles.emptyIconText}>{icon}</Text></View><Text style={styles.emptyTitle}>{title}</Text><Text style={styles.emptyDescription}>{description}</Text><Text style={styles.emptyNote}>No sample health data is shown.</Text></View>;
}

function MedicalHistory({ profile, onRead }: { profile: PatientProfile | null; onRead: () => void }) {
  return <View style={styles.stack}>
    <View style={styles.sectionHeading}><Text style={styles.sectionTitle}>Your medical information</Text><Text style={styles.sectionHint}>Information you or your care team have recorded</Text></View>
    <View style={styles.historyCard}><Detail label="Known allergies" value={profile?.allergies} empty="No allergies recorded" /><Detail label="Medical history" value={profile?.medical_history} empty="No medical history recorded" /><Detail label="Emergency contact" value={[profile?.emergency_contact_name, profile?.emergency_contact_phone].filter(Boolean).join(" · ")} empty="No emergency contact recorded" /><Detail label="Preferred language" value={profile?.preferred_language?.toUpperCase()} empty="Not set" /></View>
    <Button label="Read this information aloud" secondary onPress={onRead} />
  </View>;
}

function Detail({ label, value, empty }: { label: string; value?: string | null; empty: string }) {
  return <View style={styles.detailRow}><Text style={styles.detailLabel}>{label}</Text><Text style={[styles.detailValue, !value && styles.muted]}>{value || empty}</Text></View>;
}

function SettingsScreen({ profile, draft, update, save, saving }: { profile: PatientProfile | null; draft: Partial<PatientProfile>; update: (field: keyof PatientProfile, value: string) => void; save: () => void; saving: boolean }) {
  if (!profile) return <UnavailableCard icon="⚙" title="Settings" description="Your profile could not be loaded. Please check your connection and try again." />;
  return <View style={styles.stack}>
    <View style={styles.sectionHeading}><Text style={styles.sectionTitle}>Your profile</Text><Text style={styles.sectionHint}>Keep your information current for your care team.</Text></View>
    <View style={styles.formCard}>
      <FormField label="Full name" value={draft.name ?? ""} onChange={(value) => update("name", value)} />
      <FormField label="Date of birth" value={draft.date_of_birth ?? ""} placeholder="YYYY-MM-DD" onChange={(value) => update("date_of_birth", value)} />
      <FormField label="Phone number" value={draft.phone ?? ""} keyboardType="phone-pad" onChange={(value) => update("phone", value)} />
      <FormField label="Preferred language" value={draft.preferred_language ?? "en"} onChange={(value) => update("preferred_language", value)} />
      <Text style={styles.formSection}>Emergency contact</Text>
      <FormField label="Contact name" value={draft.emergency_contact_name ?? ""} onChange={(value) => update("emergency_contact_name", value)} />
      <FormField label="Contact phone" value={draft.emergency_contact_phone ?? ""} keyboardType="phone-pad" onChange={(value) => update("emergency_contact_phone", value)} />
      <Button label={saving ? "Saving…" : "Save changes"} onPress={save} disabled={saving} />
    </View>
    <Text style={styles.sectionHint}>Medical history and allergies are visible under Medical History. To correct them, please contact your care team.</Text>
  </View>;
}

function FormField({ label, value, onChange, placeholder, keyboardType }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; keyboardType?: "default" | "phone-pad" }) {
  return <View style={styles.formField}><Text style={styles.fieldLabel}>{label}</Text><TextInput accessibilityLabel={label} style={styles.input} value={value} onChangeText={onChange} placeholder={placeholder} keyboardType={keyboardType ?? "default"} /></View>;
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: "#f5f8f7" },
  authPage: { flex: 1, backgroundColor: "#eef6f4" },
  authContent: { flexGrow: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  brand: { color: "#12635d", fontSize: 15, letterSpacing: 2, fontWeight: "800", marginBottom: 18 },
  authCard: { width: "100%", maxWidth: 480, padding: 28, borderRadius: 24, backgroundColor: "#fff", borderWidth: 1, borderColor: "#d8e5e2" },
  authIcon: { color: "#08716b", fontSize: 42, fontWeight: "700" },
  authTitle: { color: "#153a38", fontSize: 34, fontWeight: "800", marginTop: 8 },
  authLead: { color: "#496260", fontSize: 18, lineHeight: 27, marginTop: 6, marginBottom: 18 },
  input: { minHeight: 54, borderWidth: 1, borderColor: "#9aafab", borderRadius: 12, paddingHorizontal: 15, fontSize: 18, color: "#193b39", backgroundColor: "#fff", marginTop: 11 },
  authSwitch: { minHeight: 52, alignItems: "center", justifyContent: "center", marginTop: 8 },
  authSwitchText: { color: "#075e58", fontSize: 17, fontWeight: "700", textAlign: "center" },
  privacyNote: { color: "#496260", fontSize: 15, maxWidth: 480, textAlign: "center", lineHeight: 23, marginTop: 20 },
  topbar: { minHeight: 78, backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: "#dbe6e3", flexDirection: "row", alignItems: "center", paddingHorizontal: 18, gap: 12 },
  brandMark: { width: 48, height: 48, borderRadius: 16, backgroundColor: "#08716b", alignItems: "center", justifyContent: "center" },
  brandMarkText: { color: "#fff", fontSize: 32, fontWeight: "600", lineHeight: 38 },
  topTitleWrap: { flex: 1 },
  topBrand: { color: "#12635d", fontWeight: "800", fontSize: 13, letterSpacing: 1.4 },
  topSubtitle: { color: "#183a38", fontSize: 19, fontWeight: "700", marginTop: 2 },
  readButton: { minHeight: 48, paddingHorizontal: 13, borderColor: "#9bb7b2", borderWidth: 1, borderRadius: 12, flexDirection: "row", alignItems: "center", gap: 7 },
  readIcon: { color: "#075e58", fontSize: 18, fontWeight: "800" },
  readText: { color: "#075e58", fontSize: 15, fontWeight: "700" },
  layout: { flex: 1 },
  layoutWide: { flexDirection: "row" },
  sidebar: { width: 252, backgroundColor: "#fff", borderRightWidth: 1, borderRightColor: "#dbe6e3" },
  sidebarContent: { padding: 16, gap: 5 },
  navHeading: { color: "#657c79", fontSize: 12, fontWeight: "800", letterSpacing: 1.4, margin: 12 },
  sideNavItem: { minHeight: 54, borderRadius: 13, paddingHorizontal: 13, flexDirection: "row", alignItems: "center", gap: 13 },
  sideNavActive: { backgroundColor: "#e4f3f0" },
  sideIcon: { width: 26, textAlign: "center", color: "#54716d", fontSize: 23, fontWeight: "700" },
  sideLabel: { color: "#354e4b", fontSize: 15, fontWeight: "600", flex: 1 },
  signOut: { minHeight: 52, justifyContent: "center", paddingHorizontal: 14, marginTop: 12, borderTopWidth: 1, borderTopColor: "#e3ece9" },
  signOutText: { color: "#6d403e", fontSize: 16, fontWeight: "700" },
  mainScroll: { flex: 1 },
  mainContent: { width: "100%", maxWidth: 1120, alignSelf: "center", padding: 20, paddingBottom: 40, gap: 18 },
  pageHeading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 2 },
  eyebrow: { color: "#08716b", fontSize: 12, letterSpacing: 1.7, fontWeight: "800" },
  pageTitle: { color: "#173b38", fontSize: 32, lineHeight: 39, fontWeight: "800", marginTop: 3 },
  mobileLogout: { minHeight: 44, justifyContent: "center", paddingHorizontal: 14 },
  mobileLogoutText: { color: "#075e58", fontWeight: "700", fontSize: 15 },
  loading: { minHeight: 180, alignItems: "center", justifyContent: "center", gap: 12 },
  loadingText: { color: "#35524f", fontSize: 17 },
  stack: { gap: 15 },
  welcomeCard: { backgroundColor: "#e3f2ef", borderRadius: 22, minHeight: 155, padding: 23, flexDirection: "row", alignItems: "center", overflow: "hidden" },
  welcomeCopy: { flex: 1 },
  welcomeEyebrow: { color: "#12635d", fontSize: 13, fontWeight: "800", letterSpacing: 1.3 },
  welcomeTitle: { color: "#153e3a", fontSize: 32, fontWeight: "800", marginTop: 5 },
  welcomeSub: { color: "#355a56", fontSize: 17, lineHeight: 25, marginTop: 5, maxWidth: 510 },
  welcomeArt: { color: "#87bdb4", fontSize: 76, fontWeight: "700", marginLeft: 8 },
  assistantCard: { backgroundColor: "#075e58", borderRadius: 18, padding: 18, minHeight: 90, flexDirection: "row", alignItems: "center", gap: 14 },
  assistantIcon: { width: 52, height: 52, borderRadius: 16, backgroundColor: "#e0f3ef", alignItems: "center", justifyContent: "center" },
  assistantIconText: { fontSize: 32, color: "#075e58", fontWeight: "800" },
  assistantCopy: { flex: 1 },
  assistantTitle: { color: "#fff", fontSize: 19, fontWeight: "800" },
  assistantDescription: { color: "#e3f5f1", fontSize: 15, lineHeight: 21, marginTop: 3 },
  assistantArrow: { color: "#fff", fontSize: 32, fontWeight: "500" },
  sectionHeading: { marginTop: 4, gap: 3 },
  sectionTitle: { color: "#193d39", fontSize: 21, fontWeight: "800" },
  sectionHint: { color: "#57716d", fontSize: 15, lineHeight: 22 },
  cardGrid: { flexDirection: "row", flexWrap: "wrap", gap: 13 },
  infoCard: { flexGrow: 1, flexBasis: 230, minWidth: 220, backgroundColor: "#fff", borderWidth: 1, borderColor: "#d8e4e1", borderRadius: 18, padding: 17, minHeight: 190 },
  infoIcon: { width: 42, height: 42, borderRadius: 13, alignItems: "center", justifyContent: "center", backgroundColor: "#e7f3f1" },
  infoIconText: { color: "#08716b", fontSize: 24, fontWeight: "800" },
  infoTitle: { color: "#203f3b", fontSize: 18, fontWeight: "800", marginTop: 12 },
  cardBody: { color: "#516864", fontSize: 15, lineHeight: 22, marginTop: 7 },
  textAction: { minHeight: 42, justifyContent: "center", marginTop: 7, alignSelf: "flex-start" },
  textActionText: { color: "#075e58", fontSize: 15, fontWeight: "800" },
  summaryCard: { backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#d8e4e1", padding: 18 },
  summaryHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  summaryIcon: { color: "#08716b", fontSize: 25, fontWeight: "800" },
  emptyCard: { minHeight: 280, backgroundColor: "#fff", borderWidth: 1, borderColor: "#d8e4e1", borderRadius: 20, padding: 25, alignItems: "center", justifyContent: "center" },
  emptyIcon: { width: 65, height: 65, borderRadius: 20, backgroundColor: "#e5f3f0", alignItems: "center", justifyContent: "center" },
  emptyIconText: { color: "#08716b", fontSize: 33, fontWeight: "800" },
  emptyTitle: { color: "#193d39", fontSize: 23, fontWeight: "800", textAlign: "center", marginTop: 14 },
  emptyDescription: { maxWidth: 520, color: "#516864", fontSize: 17, lineHeight: 25, textAlign: "center", marginTop: 8 },
  emptyNote: { color: "#6b807c", fontSize: 14, marginTop: 17 },
  historyCard: { backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#d8e4e1", paddingHorizontal: 18 },
  detailRow: { paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: "#e5edeb", gap: 6 },
  detailLabel: { color: "#4d6662", fontSize: 15, fontWeight: "700" },
  detailValue: { color: "#203f3b", fontSize: 18, lineHeight: 25 },
  muted: { color: "#778b88" },
  formCard: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#d8e4e1", borderRadius: 18, padding: 18 },
  formField: { marginBottom: 7 },
  fieldLabel: { color: "#304c48", fontSize: 15, fontWeight: "700", marginTop: 7 },
  formSection: { color: "#193d39", fontSize: 19, fontWeight: "800", marginTop: 17, borderTopWidth: 1, borderTopColor: "#e4ece9", paddingTop: 16 },
  primaryButton: { minHeight: 56, paddingHorizontal: 20, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: "#075e58", marginTop: 12 },
  primaryButtonText: { color: "#fff", fontSize: 18, fontWeight: "800", textAlign: "center" },
  secondaryButton: { backgroundColor: "#e7f3f1", borderWidth: 1, borderColor: "#a6c5bf" },
  secondaryButtonText: { color: "#075e58" },
  disabledButton: { opacity: 0.6 },
  feedback: { color: "#7d342d", backgroundColor: "#fff2ef", padding: 13, borderRadius: 11, fontSize: 16, lineHeight: 23, overflow: "hidden" },
  footer: { color: "#667d79", fontSize: 14, lineHeight: 21, marginTop: 3 },
  bottomNav: { flexGrow: 0, backgroundColor: "#fff", borderTopWidth: 1, borderTopColor: "#d5e2df", maxHeight: 75 },
  bottomNavContent: { paddingHorizontal: 5, alignItems: "center" },
  tabItem: { minWidth: 77, maxWidth: 104, minHeight: 66, paddingHorizontal: 7, paddingVertical: 5, borderRadius: 12, alignItems: "center", justifyContent: "center", marginHorizontal: 2 },
  tabActive: { backgroundColor: "#e4f3f0" },
  tabIcon: { color: "#58716d", fontSize: 21, fontWeight: "800", lineHeight: 24 },
  tabLabel: { color: "#425c58", fontSize: 12, lineHeight: 15, fontWeight: "700", textAlign: "center" },
  activeIcon: { color: "#075e58" },
  activeLabel: { color: "#075e58" },
});

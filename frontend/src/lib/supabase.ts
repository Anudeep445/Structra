import { createClient } from "@supabase/supabase-js";

const rawSupabaseUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined) || "";
const rawSupabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) || "";
const isDemoMode =
  !rawSupabaseUrl ||
  !rawSupabaseAnonKey ||
  rawSupabaseUrl.includes("example") ||
  rawSupabaseUrl.includes("demo") ||
  rawSupabaseAnonKey.includes("demo");

/**
 * The key we store in localStorage to track the user's "Remember me" choice.
 * This is a tiny string flag — it does NOT contain any credentials.
 */
export const STORAGE_PREF_KEY = "structra_remember_me";
const DEMO_SESSION_KEY = "structra_demo_session";
const DEMO_USERS_KEY = "structra_demo_users";

/**
 * Custom storage adapter.
 *
 * • "Remember me" ON  → store session in localStorage  (survives browser restarts)
 * • "Remember me" OFF → store session in sessionStorage (cleared when tab/window closes)
 *
 * Reading falls back to localStorage so that an existing remembered session
 * is always found, regardless of where we are in the preference toggle.
 */
const rememberMeStorage = {
  getItem(key: string): string | null {
    return sessionStorage.getItem(key) ?? localStorage.getItem(key);
  },
  setItem(key: string, value: string): void {
    const remember = localStorage.getItem(STORAGE_PREF_KEY) === "true";
    if (remember) {
      localStorage.setItem(key, value);
      sessionStorage.removeItem(key);
    } else {
      sessionStorage.setItem(key, value);
      localStorage.removeItem(key);
    }
  },
  removeItem(key: string): void {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  },
};

function createDemoSession(user: any) {
  return {
    access_token: `demo_access_${user.id}`,
    refresh_token: `demo_refresh_${user.id}`,
    expires_in: 3600,
    expires_at: Math.floor((Date.now() + 3600 * 1000) / 1000),
    token_type: "bearer",
    user,
  };
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value));
}

function createDemoAuth() {
  const listeners = new Set<(event: string, session: any) => void>();
  const getUsers = () => readJson<any[]>(DEMO_USERS_KEY, []);
  const saveUsers = (users: any[]) => writeJson(DEMO_USERS_KEY, users);
  const getSession = () => readJson<any | null>(DEMO_SESSION_KEY, null);
  const saveSession = (session: any | null) => {
    if (session) {
      writeJson(DEMO_SESSION_KEY, session);
    } else {
      localStorage.removeItem(DEMO_SESSION_KEY);
    }
  };
  const emitAuthChange = (event: string, session: any | null) => {
    listeners.forEach((callback) => callback(event, session));
  };

  return {
    onAuthStateChange: (callback: (event: string, session: any) => void) => {
      listeners.add(callback);
      const currentSession = getSession();
      callback("INITIAL_SESSION", currentSession);
      return {
        data: {
          subscription: {
            unsubscribe: () => listeners.delete(callback),
          },
        },
      };
    },
    signInWithPassword: async ({ email, password }: { email: string; password: string }) => {
      const users = getUsers();
      const record = users.find(
        (user) => user.email.toLowerCase() === email.toLowerCase() && user.password === password
      );

      if (!record) {
        return {
          data: { user: null, session: null },
          error: { message: "Invalid login credentials", name: "AuthApiError" },
        };
      }

      const user = {
        ...record,
        email_confirmed_at: new Date().toISOString(),
        user_metadata: {
          ...record.user_metadata,
          full_name: record.user_metadata?.full_name || record.email.split("@")[0],
        },
      };

      const session = createDemoSession(user);
      saveSession(session);
      emitAuthChange("SIGNED_IN", session);
      return { data: { user, session }, error: null };
    },
    signUp: async ({ email, password, options }: { email: string; password: string; options?: any }) => {
      const users = getUsers();
      const existing = users.find((user) => user.email.toLowerCase() === email.toLowerCase());

      if (existing) {
        return {
          data: {
            user: { ...existing, identities: [] },
            session: null,
          },
          error: null,
        };
      }

      const user = {
        id: typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `demo-user-${Date.now()}`,
        aud: "authenticated",
        email,
        password,
        email_confirmed_at: new Date().toISOString(),
        app_metadata: { provider: "demo" },
        user_metadata: {
          full_name: options?.data?.full_name || email.split("@")[0],
          avatar_url: null,
          picture: null,
        },
        identities: [{ id: `demo-${Date.now()}`, provider: "demo" }],
      };

      users.push(user);
      saveUsers(users);

      const session = createDemoSession(user);
      saveSession(session);
      emitAuthChange("SIGNED_IN", session);
      return { data: { user, session }, error: null };
    },
    signOut: async () => {
      saveSession(null);
      emitAuthChange("SIGNED_OUT", null);
      return { error: null };
    },
    resend: async () => ({ error: null }),
    resetPasswordForEmail: async () => ({ error: null }),
    updateUser: async ({ password, data }: { password?: string; data?: Record<string, any> }) => {
      const session = getSession();
      if (!session) {
        return { data: { user: null }, error: { message: "No active session", name: "AuthApiError" } };
      }

      const users = getUsers();
      const index = users.findIndex((user) => user.email === session.user.email);
      if (index >= 0) {
        const updatedUser = {
          ...users[index],
          user_metadata: {
            ...(users[index].user_metadata || {}),
            ...(data || {}),
          },
        };
        if (password) {
          updatedUser.password = password;
        }
        users[index] = updatedUser;
        saveUsers(users);
        const nextSession = createDemoSession(updatedUser);
        saveSession(nextSession);
        return { data: { user: updatedUser }, error: null };
      }

      return { data: { user: session.user }, error: null };
    },
    refreshSession: async () => {
      const session = getSession();
      return {
        data: { session, user: session?.user ?? null },
        error: null,
      };
    },
    getSession: async () => {
      const session = getSession();
      return {
        data: { session: session ?? null },
        error: null,
      };
    },
    getUser: async () => {
      const session = getSession();
      return { data: { user: session?.user ?? null }, error: null };
    },
    signInWithOAuth: async () => {
      const users = getUsers();
      const demoUser = users[0] || {
        id: "demo-google-user",
        email: "demo@structra.app",
        password: "demo123",
        user_metadata: { full_name: "Demo User", avatar_url: null, picture: null },
        email_confirmed_at: new Date().toISOString(),
        app_metadata: { provider: "google" },
        aud: "authenticated",
      };

      const session = createDemoSession(demoUser);
      saveSession(session);
      emitAuthChange("SIGNED_IN", session);
      return { data: { user: demoUser, session }, error: null };
    },
  };
}

const demoSupabase = { auth: createDemoAuth() } as any;

export const supabase = isDemoMode
  ? demoSupabase
  : createClient(rawSupabaseUrl, rawSupabaseAnonKey, {
      auth: {
        storage: rememberMeStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    });

if (!isDemoMode && (!rawSupabaseUrl || !rawSupabaseAnonKey)) {
  throw new Error(
    "Missing Supabase environment variables. Ensure VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are set in your .env file."
  );
}


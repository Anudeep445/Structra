import { supabase } from '../lib/supabase';

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

/**
 * Helper to retrieve the current user's JWT access token for authenticated API calls.
 */
async function getAuthToken() {
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error || !session) {
    throw new Error('Authentication required. Please sign in again.');
  }
  return session.access_token;
}

/**
 * Generic JSON fetcher with authorization header and error extraction.
 */
async function fetchJson(endpoint, options = {}) {
  const token = await getAuthToken();
  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = { detail: response.statusText };
    }
    const msg = typeof errorData.detail === 'string'
      ? errorData.detail
      : (errorData.detail?.[0]?.msg || 'Profile request failed.');
    throw new Error(msg);
  }

  return await response.json();
}

/**
 * Fetches authenticated user profile, account details, and usage metrics.
 */
export async function getProfile() {
  const profile = await fetchJson('/profile');
  const { data: { session } } = await supabase.auth.getSession();
  const authUser = session?.user;
  const authName =
    authUser?.user_metadata?.full_name ||
    authUser?.user_metadata?.name ||
    authUser?.name ||
    authUser?.email?.split('@')[0];

  // In demo mode the backend has no access to browser-local auth metadata.
  // Use the authenticated session's name so profile cards match the top bar.
  if (profile?.user && (authName || authUser?.email)) {
    return {
      ...profile,
      user: {
        ...profile.user,
        ...(authName ? { name: authName } : {}),
        ...(authUser?.email ? { email: authUser.email } : {}),
      },
    };
  }

  return profile;
}

/**
 * Updates personal information fields (name, phone, organization, job title, location).
 */
export async function updateProfile(profileData) {
  return await fetchJson('/profile', {
    method: 'PATCH',
    body: JSON.stringify(profileData),
  });
}

/**
 * Uploads a new custom profile picture (JPG, PNG, WEBP <= 2 MB).
 */
export async function uploadProfilePicture(file) {
  const token = await getAuthToken();
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_URL}/profile/picture`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
    body: formData,
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = { detail: response.statusText };
    }
    const msg = typeof errorData.detail === 'string'
      ? errorData.detail
      : (errorData.detail?.[0]?.msg || 'Profile picture upload failed.');
    throw new Error(msg);
  }

  return await response.json();
}

/**
 * Deletes custom profile picture and restores account letter avatar.
 */
export async function deleteProfilePicture() {
  const token = await getAuthToken();
  const response = await fetch(`${API_URL}/profile/picture`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = { detail: response.statusText };
    }
    const msg = typeof errorData.detail === 'string'
      ? errorData.detail
      : (errorData.detail?.[0]?.msg || 'Failed to remove profile picture.');
    throw new Error(msg);
  }

  return await response.json();
}

/**
 * Fetches real account & security overview (providers, password status, active sessions).
 */
export async function getSecurityOverview() {
  return await fetchJson('/profile/security');
}

/**
 * Fetches chronological security activity audit logs for the current user.
 */
export async function getSecurityActivity() {
  return await fetchJson('/profile/security/activity');
}

/**
 * Logs an authenticated security event into the audit log.
 * @param {{ event_type: string, description: string, device_info?: string }} activityData
 */
export async function recordSecurityActivity(activityData) {
  return await fetchJson('/profile/security/activity', {
    method: 'POST',
    body: JSON.stringify(activityData),
  });
}

/**
 * Permanently deletes the authenticated user account and all associated data.
 * @param {string} confirmation - Must be exactly 'DELETE'
 */
export async function deleteAccount(confirmation) {
  return await fetchJson('/profile/account', {
    method: 'DELETE',
    body: JSON.stringify({ confirmation }),
  });
}


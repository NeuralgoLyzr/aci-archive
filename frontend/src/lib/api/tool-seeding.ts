export interface SeedingRequest {
  app_path: string;
  functions_path?: string;
  secrets?: Record<string, string>;
  skip_dry_run?: boolean;
}

export interface SeedingResponse {
  success: boolean;
  message: string;
  app_id?: string;
  function_ids?: string[];
  errors?: string[];
}

export interface SeedingStatus {
  is_running: boolean;
  current_operation?: string;
  progress?: string;
}

export interface AvailableApp {
  name: string;
  display_name: string;
  description: string;
  app_path: string;
  functions_path?: string;
  requires_secrets: boolean;
  auth_schemes: Record<string, unknown>[];
}

export interface SeededApp {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  visibility_access: string;
  created_at?: string;
  updated_at?: string;
  function_count: number;
}

export async function getSeedingStatus(
  accessToken: string,
  orgId: string,
): Promise<SeedingStatus> {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/v1/tool-seeding/seeding-status`,
    {
      method: "GET",
      headers: {
        "X-ACI-ORG-ID": orgId,
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to get seeding status: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

export async function seedTool(
  accessToken: string,
  orgId: string,
  request: SeedingRequest,
): Promise<SeedingResponse> {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/v1/tool-seeding/seed-tool`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ACI-ORG-ID": orgId,
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to seed tool: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

export async function getAvailableApps(
  accessToken: string,
  orgId: string,
): Promise<AvailableApp[]> {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/v1/tool-seeding/available-apps`,
    {
      method: "GET",
      headers: {
        "X-ACI-ORG-ID": orgId,
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to get available apps: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

export async function getSeededApps(
  accessToken: string,
  orgId: string,
): Promise<SeededApp[]> {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/v1/tool-seeding/seeded-apps`,
    {
      method: "GET",
      headers: {
        "X-ACI-ORG-ID": orgId,
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to get seeded apps: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

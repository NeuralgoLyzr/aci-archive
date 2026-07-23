"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useMetaInfo } from "@/components/context/metainfo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Play,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Loader2,
  Settings,
  Database,
  Plus,
  Key,
} from "lucide-react";
import { toast } from "sonner";
import {
  getSeedingStatus,
  seedTool,
  getAvailableApps,
  getSeededApps,
  type SeedingRequest,
  type AvailableApp,
  type SeededApp,
  type SeedingStatus,
} from "@/lib/api/tool-seeding";

export default function ToolSeedingPage() {
  const { accessToken, activeOrg } = useMetaInfo();

  // Form state
  const [selectedApp, setSelectedApp] = useState<AvailableApp | null>(null);
  const [customAppPath, setCustomAppPath] = useState("");
  const [customFunctionsPath, setCustomFunctionsPath] = useState("");
  const [secrets, setSecrets] = useState("");
  const [skipDryRun, setSkipDryRun] = useState(true);
  const [useCustomPaths, setUseCustomPaths] = useState(false);

  // Data state
  const [availableApps, setAvailableApps] = useState<AvailableApp[]>([]);
  const [seededApps, setSeededApps] = useState<SeededApp[]>([]);
  const [seedingStatus, setSeedingStatus] = useState<SeedingStatus | null>(
    null,
  );

  // Loading state
  const [isLoading, setIsLoading] = useState(false);
  const [isSeeding, setIsSeeding] = useState(false);

  const loadData = useCallback(async () => {
    if (!activeOrg) return;

    setIsLoading(true);
    try {
      const [apps, seeded, status] = await Promise.all([
        getAvailableApps(accessToken, activeOrg.orgId),
        getSeededApps(accessToken, activeOrg.orgId),
        getSeedingStatus(accessToken, activeOrg.orgId),
      ]);
      setAvailableApps(apps);
      setSeededApps(seeded);
      setSeedingStatus(status);
    } catch (error: unknown) {
      console.error("Failed to load data:", error);
      toast.error("Failed to load data");
    } finally {
      setIsLoading(false);
    }
  }, [accessToken, activeOrg]);

  const checkSeedingStatus = useCallback(async () => {
    if (!activeOrg) return;

    try {
      const status = await getSeedingStatus(accessToken, activeOrg.orgId);
      setSeedingStatus(status);

      if (status.is_running) {
        setIsSeeding(true);
      } else if (isSeeding && !status.is_running) {
        // Seeding just finished
        setIsSeeding(false);
        await loadData(); // Refresh the seeded apps list
        toast.success("Seeding completed!");
      }
    } catch (error: unknown) {
      console.error("Failed to check seeding status:", error);
    }
  }, [accessToken, activeOrg, isSeeding, loadData]);

  useEffect(() => {
    loadData();
    const interval = setInterval(checkSeedingStatus, 2000);
    return () => clearInterval(interval);
  }, [loadData, checkSeedingStatus]);

  const handleSeedTool = async () => {
    if (!activeOrg) {
      toast.error("No organization selected");
      return;
    }

    if (!useCustomPaths && !selectedApp) {
      toast.error("Please select an app to seed");
      return;
    }

    if (useCustomPaths && !customAppPath) {
      toast.error("Please enter an app path");
      return;
    }

    try {
      setIsSeeding(true);

      let parsedSecrets: Record<string, string> = {};
      if (secrets.trim()) {
        try {
          parsedSecrets = JSON.parse(secrets);
        } catch {
          toast.error("Invalid JSON format in secrets");
          setIsSeeding(false);
          return;
        }
      }

      const request: SeedingRequest = {
        app_path: useCustomPaths ? customAppPath : selectedApp!.app_path,
        functions_path: useCustomPaths
          ? customFunctionsPath || undefined
          : selectedApp!.functions_path,
        secrets:
          Object.keys(parsedSecrets).length > 0 ? parsedSecrets : undefined,
        skip_dry_run: skipDryRun,
      };

      const response = await seedTool(accessToken, activeOrg.orgId, request);

      if (response.success) {
        toast.success(response.message);
      } else {
        toast.error(response.message);
        setIsSeeding(false);
      }
    } catch (error: unknown) {
      console.error("Failed to seed tool:", error);
      toast.error("Failed to seed tool");
      setIsSeeding(false);
    }
  };

  const renderSeedingProgress = () => {
    if (!seedingStatus?.is_running) return null;

    const progressValue = seedingStatus.progress
      ? (parseInt(seedingStatus.progress.split("/")[0]) /
          parseInt(seedingStatus.progress.split("/")[1])) *
        100
      : 0;

    return (
      <Alert className="mb-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        <AlertDescription>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span>{seedingStatus.current_operation}</span>
              <span className="text-sm text-muted-foreground">
                {seedingStatus.progress}
              </span>
            </div>
            <Progress value={progressValue} className="w-full" />
          </div>
        </AlertDescription>
      </Alert>
    );
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Settings className="h-8 w-8" />
            Tool Seeding Management
          </h1>
          <p className="text-muted-foreground mt-2">
            Manage and deploy tools to your ACI instance without requiring CLI
            access or Docker commands.
          </p>
        </div>
        <Button onClick={loadData} variant="outline" disabled={isLoading}>
          <RefreshCw
            className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {renderSeedingProgress()}

      <Tabs defaultValue="seed" className="space-y-6">
        <TabsList>
          <TabsTrigger value="seed">Seed New Tool</TabsTrigger>
          <TabsTrigger value="available">
            Available Apps ({availableApps.length})
          </TabsTrigger>
          <TabsTrigger value="seeded">
            Seeded Apps ({seededApps.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="seed" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plus className="h-5 w-5" />
                Seed New Tool
              </CardTitle>
              <CardDescription>
                Deploy a new tool integration by selecting from available apps
                or providing custom paths.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center space-x-2">
                <Switch
                  id="custom-paths"
                  checked={useCustomPaths}
                  onCheckedChange={setUseCustomPaths}
                />
                <Label htmlFor="custom-paths">
                  Use custom paths instead of selecting from available apps
                </Label>
              </div>

              {!useCustomPaths ? (
                <div className="space-y-2">
                  <Label htmlFor="app-select">Select App</Label>
                  <Select
                    value={selectedApp?.name || ""}
                    onValueChange={(value: string) => {
                      const app = availableApps.find(
                        (a: AvailableApp) => a.name === value,
                      );
                      setSelectedApp(app || null);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose an app to seed..." />
                    </SelectTrigger>
                    <SelectContent>
                      {availableApps.map((app: AvailableApp) => (
                        <SelectItem key={app.name} value={app.name}>
                          <div className="flex items-center justify-between w-full">
                            <span>{app.display_name}</span>
                            {app.requires_secrets && (
                              <Badge variant="outline" className="ml-2">
                                <Key className="h-3 w-3 mr-1" />
                                OAuth
                              </Badge>
                            )}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {selectedApp && (
                    <div className="p-3 bg-muted rounded-lg">
                      <p className="text-sm">{selectedApp.description}</p>
                      <div className="mt-2 space-y-1">
                        <p className="text-xs text-muted-foreground">
                          App Path: {selectedApp.app_path}
                        </p>
                        {selectedApp.functions_path && (
                          <p className="text-xs text-muted-foreground">
                            Functions Path: {selectedApp.functions_path}
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="app-path">App JSON Path</Label>
                    <Input
                      id="app-path"
                      placeholder="./apps/your-app/app.json"
                      value={customAppPath}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        setCustomAppPath(e.target.value)
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="functions-path">
                      Functions JSON Path (Optional)
                    </Label>
                    <Input
                      id="functions-path"
                      placeholder="./apps/your-app/functions.json"
                      value={customFunctionsPath}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        setCustomFunctionsPath(e.target.value)
                      }
                    />
                  </div>
                </div>
              )}

              {(selectedApp?.requires_secrets || useCustomPaths) && (
                <div className="space-y-2">
                  <Label htmlFor="secrets">OAuth2 Secrets (JSON format)</Label>
                  <Textarea
                    id="secrets"
                    placeholder={`{
  "CLIENT_ID": "your-client-id",
  "CLIENT_SECRET": "your-client-secret"
}`}
                    value={secrets}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                      setSecrets(e.target.value)
                    }
                    rows={6}
                  />
                  <p className="text-xs text-muted-foreground">
                    Enter OAuth2 credentials in JSON format. Only required for
                    apps that use OAuth2 authentication.
                  </p>
                </div>
              )}

              <div className="flex items-center space-x-2">
                <Switch
                  id="skip-dry-run"
                  checked={skipDryRun}
                  onCheckedChange={setSkipDryRun}
                />
                <Label htmlFor="skip-dry-run">
                  Apply changes immediately (skip dry run)
                </Label>
              </div>

              <Button
                onClick={handleSeedTool}
                disabled={isSeeding || seedingStatus?.is_running}
                className="w-full"
              >
                {isSeeding ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Seeding Tool...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Seed Tool
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="available" className="space-y-4">
          {availableApps.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                No available apps found. Make sure your apps directory contains
                valid app configurations.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {availableApps.map((app: AvailableApp) => (
                <Card key={app.name} className="h-full">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-lg">
                        {app.display_name}
                      </CardTitle>
                      {app.requires_secrets && (
                        <Badge variant="outline">
                          <Key className="h-3 w-3 mr-1" />
                          OAuth
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      {app.description}
                    </p>
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">
                        App: {app.app_path}
                      </p>
                      {app.functions_path && (
                        <p className="text-xs text-muted-foreground">
                          Functions: {app.functions_path}
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      className="w-full"
                      onClick={() => {
                        setSelectedApp(app);
                        setUseCustomPaths(false);
                      }}
                      disabled={isSeeding || seedingStatus?.is_running}
                    >
                      Select for Seeding
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="seeded" className="space-y-4">
          {seededApps.length === 0 ? (
            <Alert>
              <Database className="h-4 w-4" />
              <AlertDescription>
                No apps have been seeded yet. Use the &quot;Seed New Tool&quot;
                tab to deploy your first tool.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="grid gap-4">
              {seededApps.map((app: SeededApp) => (
                <Card key={app.id}>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <CardTitle className="text-lg">
                          {app.display_name}
                        </CardTitle>
                        <CardDescription>{app.description}</CardDescription>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary">
                          {app.function_count} function
                          {app.function_count !== 1 ? "s" : ""}
                        </Badge>
                        <Badge variant="outline">{app.category}</Badge>
                        <CheckCircle className="h-5 w-5 text-green-500" />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">
                          Visibility:
                        </span>
                        <span className="ml-2 capitalize">
                          {app.visibility_access}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Created:</span>
                        <span className="ml-2">
                          {app.created_at
                            ? new Date(app.created_at).toLocaleDateString()
                            : "Unknown"}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

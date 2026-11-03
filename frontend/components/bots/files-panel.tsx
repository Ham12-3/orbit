"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Download, File, Folder, FolderOpen, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorNote } from "@/components/error-note";
import { Markdown } from "@/components/markdown";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { backendUrl } from "@/lib/api";
import { fileSize, timeAgo } from "@/lib/format";
import { fileUrl, keys, useFileContent, useRefreshWorkspace, useWorkspace } from "@/lib/queries";
import type { Bot, FileEntry } from "@/lib/types";
import { useAfterRun } from "@/lib/use-after-run";
import { cn } from "@/lib/utils";

const PREVIEW_MAX_BYTES = 1024 * 1024;
const IMAGE_TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
};

interface TreeNode {
  entry: FileEntry;
  name: string;
  children: TreeNode[];
}

function buildTree(entries: FileEntry[]): TreeNode[] {
  const nodes = new Map<string, TreeNode>();
  for (const entry of entries) {
    nodes.set(entry.path, { entry, name: entry.path.split("/").at(-1) ?? entry.path, children: [] });
  }
  const roots: TreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.entry.path.includes("/")
      ? nodes.get(node.entry.path.slice(0, node.entry.path.lastIndexOf("/")))
      : undefined;
    (parent ? parent.children : roots).push(node);
  }
  const sort = (list: TreeNode[]) => {
    list.sort((a, b) =>
      a.entry.kind === b.entry.kind ? a.name.localeCompare(b.name) : a.entry.kind === "dir" ? -1 : 1,
    );
    list.forEach((node) => sort(node.children));
  };
  sort(roots);
  return roots;
}

function extension(path: string): string {
  const name = path.split("/").at(-1) ?? "";
  return name.includes(".") ? (name.split(".").at(-1) ?? "").toLowerCase() : "";
}

export function FilesPanel({ bot }: { bot: Bot }) {
  const queryClient = useQueryClient();
  const listing = useWorkspace(bot.id);
  const refresh = useRefreshWorkspace(bot.id);
  const [selected, setSelected] = useState<string | null>(null);
  const tree = useMemo(() => buildTree(listing.data?.entries ?? []), [listing.data]);

  // The listing is taken when a run ends.
  useAfterRun(bot, () => void queryClient.invalidateQueries({ queryKey: keys.files(bot.id) }));

  const entry = listing.data?.entries.find((e) => e.path === selected && e.kind === "file");
  const scannedAt = listing.data?.scanned_at ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {bot.name}&apos;s <span className="font-mono">workspace/</span> folder, read-only.{" "}
          {scannedAt ? `Listed ${timeAgo(scannedAt)}.` : null}
        </p>
        <Button
          variant="outline"
          size="sm"
          disabled={!bot.sandbox_id || refresh.isPending}
          onClick={() => refresh.mutate()}
          title="Wakes the bot's computer for a few minutes"
        >
          <RefreshCw className={cn(refresh.isPending && "animate-spin")} />
          {refresh.isPending ? "Checking…" : "Check now"}
        </Button>
      </div>
      {refresh.isError && <ErrorNote error={refresh.error} />}
      {listing.isError && <ErrorNote error={listing.error} />}
      {listing.isPending && <Skeleton className="h-40 rounded-xl" />}

      {listing.data && listing.data.entries.length === 0 && (
        <div className="rounded-xl border border-dashed px-6 py-12 text-center">
          <Folder className="mx-auto mb-3 size-6 text-muted-foreground" />
          <p className="font-medium">
            {scannedAt ? "The workspace is empty" : "No files yet"}
          </p>
          <p className="mx-auto max-w-sm text-sm text-muted-foreground">
            {scannedAt
              ? `Ask ${bot.name} to save something in workspace/ and it shows up here.`
              : `Files appear here after ${bot.name}'s first run.`}
          </p>
        </div>
      )}

      {listing.data && listing.data.entries.length > 0 && (
        <div className="grid gap-6 md:grid-cols-[minmax(220px,320px)_1fr]">
          <aside className={cn("rounded-xl border p-2", selected && "hidden md:block")}>
            <Tree nodes={tree} depth={0} selected={selected} onSelect={setSelected} />
            {listing.data.truncated && (
              <p className="px-2 py-1 text-xs text-muted-foreground">
                Showing the first {listing.data.entries.length.toLocaleString()} items.
              </p>
            )}
          </aside>
          <section className="min-w-0">
            {selected && (
              <Button variant="ghost" size="sm" className="-ml-2 mb-2 md:hidden" onClick={() => setSelected(null)}>
                <ArrowLeft /> Files
              </Button>
            )}
            {entry ? (
              <Preview key={entry.path} bot={bot} entry={entry} />
            ) : (
              <div className="hidden rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground md:block">
                Pick a file to preview it.
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Tree({
  nodes,
  depth,
  selected,
  onSelect,
}: {
  nodes: TreeNode[];
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <ul>
      {nodes.map((node) =>
        node.entry.kind === "dir" ? (
          <DirectoryRow key={node.entry.path} node={node} depth={depth} selected={selected} onSelect={onSelect} />
        ) : (
          <li key={node.entry.path}>
            <button
              type="button"
              onClick={() => onSelect(node.entry.path)}
              style={{ paddingLeft: `${depth * 16 + 28}px` }}
              className={cn(
                "flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-sm hover:bg-muted",
                node.entry.path === selected && "bg-muted",
              )}
            >
              <File className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{node.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{fileSize(node.entry.size)}</span>
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

function DirectoryRow({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth === 0 && node.children.length <= 20);
  const Icon = open ? FolderOpen : Folder;
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        className="flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-sm hover:bg-muted"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        {node.children.length === 0 && <span className="text-xs text-muted-foreground">empty</span>}
      </button>
      {open && node.children.length > 0 && (
        <Tree nodes={node.children} depth={depth + 1} selected={selected} onSelect={onSelect} />
      )}
    </li>
  );
}

function Preview({ bot, entry }: { bot: Bot; entry: FileEntry }) {
  const tooBig = entry.size > PREVIEW_MAX_BYTES;
  const content = useFileContent(bot.id, entry.path, entry.modified_at, !tooBig);
  const name = entry.path.split("/").at(-1) ?? entry.path;
  const ext = extension(entry.path);

  return (
    <div className="space-y-3 rounded-xl border p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h3 className="truncate font-mono text-sm font-medium">workspace/{entry.path}</h3>
          <p className="text-xs text-muted-foreground">
            {fileSize(entry.size)} · changed {timeAgo(entry.modified_at)}
          </p>
        </div>
        <a
          href={backendUrl(fileUrl(bot.id, entry.path))}
          download={name}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          <Download /> Download
        </a>
      </div>
      {tooBig ? (
        <p className="text-sm text-muted-foreground">Too big to preview here. Download it instead.</p>
      ) : content.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-32" />
          <p className="text-xs text-muted-foreground">Opening the bot&apos;s computer…</p>
        </div>
      ) : content.isError ? (
        <ErrorNote error={content.error} />
      ) : (
        <FileBody bytes={content.data} ext={ext} />
      )}
    </div>
  );
}

function FileBody({ bytes, ext }: { bytes: ArrayBuffer; ext: string }) {
  const body = useMemo(() => {
    const imageType = IMAGE_TYPES[ext];
    if (imageType) {
      // A data URL in <img>: SVG scripts never run there, and nothing is navigated to.
      let binary = "";
      new Uint8Array(bytes).forEach((byte) => (binary += String.fromCharCode(byte)));
      return { kind: "image" as const, src: `data:${imageType};base64,${btoa(binary)}` };
    }
    try {
      return { kind: "text" as const, text: new TextDecoder("utf-8", { fatal: true }).decode(bytes) };
    } catch {
      return { kind: "binary" as const };
    }
  }, [bytes, ext]);

  if (body.kind === "image") {
    // eslint-disable-next-line @next/next/no-img-element -- a local data URL, not an optimisable asset
    return <img src={body.src} alt="" className="max-h-[32rem] max-w-full rounded-md border" />;
  }
  if (body.kind === "binary") {
    return <p className="text-sm text-muted-foreground">This isn&apos;t a text file. Download it to open it.</p>;
  }
  if (!body.text.trim()) return <p className="text-sm text-muted-foreground">(empty)</p>;
  if (ext === "md" || ext === "markdown") return <Markdown className="text-sm">{body.text}</Markdown>;
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
      {body.text}
    </pre>
  );
}

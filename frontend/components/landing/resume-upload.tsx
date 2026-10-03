"use client";

import { useRef, useState, type DragEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileText, Loader2, UploadCloud, X, Radar } from "lucide-react";
import { cn } from "@/lib/utils";
import { parseResume } from "@/lib/api";
import type { ResumeProfile } from "@/lib/types";

interface ResumeUploadProps {
  onSubmit: (prompt: string) => void;
  isLoading?: boolean;
}

const splitList = (value: string) =>
  value.split(",").map((v) => v.trim()).filter(Boolean);

/** Turns the (user-reviewed) profile into a normal prompt for the existing pipeline.
 *  Line 1 is the main request; each "Refine:" line is an extra constraint for the Planner.
 *  Kept SHORT on purpose: max 3 roles, 1 main city. Skills are NOT sent as search words
 *  (job boards match every word, so long keyword lists return nothing). */
function buildPrompt(p: {
  targetRoles: string[];
  experience: string;
  locations: string[];
  skills: string[];
}): string {
  const roles = (p.targetRoles.length ? p.targetRoles : ["Software Developer"]).slice(0, 3);
  const city = p.locations[0] || "";
  const lines = [`Find current job openings for these roles: ${roles.join(", ")}${city ? ` in ${city}` : ""}`];
  if (p.experience) lines.push(`Refine: Candidate experience level: ${p.experience}. Only roles suitable for this level`);
  return lines.join("\n");
}

const inputClass = cn(
  "w-full rounded-lg bg-elevated border border-border-subtle px-3 py-2",
  "text-sm text-text-primary placeholder:text-text-muted/60 outline-none",
  "focus:border-cyan/40 transition-colors"
);

export function ResumeUpload({ onSubmit, isLoading = false }: ResumeUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<"idle" | "parsing" | "review">("idle");
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");

  // Editable copy of what the Resume Agent found
  const [name, setName] = useState("");
  const [currentRole, setCurrentRole] = useState("");
  const [experience, setExperience] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [targetRoles, setTargetRoles] = useState("");
  const [locations, setLocations] = useState("");

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setFileName(file.name);
    setStep("parsing");
    try {
      const p: ResumeProfile = await parseResume(file);
      setName(p.name);
      setCurrentRole(p.current_role);
      setExperience(p.experience);
      setSkills(p.skills);
      setTargetRoles(p.target_roles.join(", "));
      setLocations(p.locations.join(", "));
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this resume");
      setStep("idle");
    }
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files?.[0]);
  };

  const reset = () => {
    setStep("idle");
    setError(null);
    setFileName("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleScan = () => {
    if (isLoading) return;
    onSubmit(
      buildPrompt({
        targetRoles: splitList(targetRoles),
        experience: experience.trim(),
        locations: splitList(locations),
        skills,
      })
    );
  };

  const canScan = splitList(targetRoles).length > 0 && !isLoading;

  return (
    <div className="w-full max-w-3xl mx-auto">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt,.md"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      <AnimatePresence mode="wait">
        {step !== "review" ? (
          <motion.div
            key="drop"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <div
              onClick={() => step === "idle" && inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={cn(
                "flex flex-col items-center justify-center gap-3 rounded-2xl px-6 py-14 text-center",
                "bg-card-solid border border-dashed transition-all duration-300",
                step === "idle" ? "cursor-pointer" : "cursor-default",
                dragOver
                  ? "border-cyan/60 shadow-[0_0_40px_rgba(0,240,255,0.15)]"
                  : "border-border-subtle hover:border-cyan/40"
              )}
            >
              {step === "parsing" ? (
                <>
                  <Loader2 className="h-8 w-8 text-cyan animate-spin" />
                  <p className="text-text-primary">Reading {fileName}...</p>
                  <p className="text-xs text-text-muted font-mono">Resume Agent is extracting your skills and roles</p>
                </>
              ) : (
                <>
                  <UploadCloud className="h-8 w-8 text-cyan" />
                  <p className="text-lg text-text-primary">Drop your resume here, or click to browse</p>
                  <p className="text-xs text-text-muted font-mono">PDF or TXT · max 5 MB · not stored</p>
                </>
              )}
            </div>
            {error && (
              <p className="mt-4 text-sm text-rose bg-rose/10 border border-rose/20 rounded-lg px-4 py-3">
                {error}
              </p>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl bg-card-solid border border-border-subtle p-6 text-left"
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <FileText className="h-4 w-4 text-cyan" />
                <span className="font-mono truncate max-w-[260px]">{fileName}</span>
              </div>
              <button
                onClick={reset}
                className="text-xs font-mono text-text-muted hover:text-cyan transition-colors"
              >
                Change resume
              </button>
            </div>

            <p className="text-xs font-mono uppercase tracking-wider text-cyan mb-1">Calibrate the radar</p>
            <p className="text-sm text-text-secondary mb-5">
              Here&apos;s what we found in your resume{name ? `, ${name}` : ""}. Fix anything that looks off, then scan.
            </p>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted">Current role</span>
                <input className={cn(inputClass, "mt-1")} value={currentRole} onChange={(e) => setCurrentRole(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted">Experience</span>
                <input className={cn(inputClass, "mt-1")} value={experience} onChange={(e) => setExperience(e.target.value)} placeholder="Fresher / 2 years" />
              </label>
              <label className="block">
                <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted">Target roles (comma separated)</span>
                <input className={cn(inputClass, "mt-1")} value={targetRoles} onChange={(e) => setTargetRoles(e.target.value)} placeholder="Full Stack Developer, Backend Developer" />
              </label>
              <label className="block">
                <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted">Locations (comma separated)</span>
                <input className={cn(inputClass, "mt-1")} value={locations} onChange={(e) => setLocations(e.target.value)} placeholder="Bengaluru, Remote" />
              </label>
            </div>

            <div className="mt-4">
              <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted">Skills (click × to remove)</span>
              <div className="mt-2 flex flex-wrap gap-2">
                {skills.map((skill) => (
                  <span
                    key={skill}
                    className="flex items-center gap-1.5 rounded-full border border-cyan/20 bg-cyan/5 px-3 py-1 text-xs text-cyan"
                  >
                    {skill}
                    <button
                      onClick={() => setSkills((prev) => prev.filter((s) => s !== skill))}
                      aria-label={`Remove ${skill}`}
                      className="hover:text-rose transition-colors"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                {skills.length === 0 && <span className="text-xs text-text-muted">No skills found</span>}
              </div>
            </div>

            <button
              onClick={handleScan}
              disabled={!canScan}
              className={cn(
                "mt-6 flex w-full items-center justify-center gap-2 rounded-xl px-5 py-3 font-semibold transition-all",
                canScan
                  ? "bg-gradient-to-br from-cyan to-violet text-void shadow-lg shadow-cyan/30 hover:scale-[1.01]"
                  : "bg-elevated text-text-muted border border-border-subtle cursor-not-allowed"
              )}
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />}
              Scan my career
            </button>
            {!canScan && !isLoading && (
              <p className="mt-2 text-center text-xs text-text-muted">Add at least one target role to scan.</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
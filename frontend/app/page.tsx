"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ParticleField } from "@/components/shared/particle-field";
import { AuroraBackground } from "@/components/shared/aurora-background";
import { HeroSection } from "@/components/landing/hero-section";
import { PromptInput } from "@/components/landing/prompt-input";
import { ResumeUpload } from "@/components/landing/resume-upload";

export default function HomePage() {
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState<"resume" | "prompt">("prompt");
  const router = useRouter();

  const handleSubmit = (prompt: string) => {
    setIsLoading(true);
    // Navigate immediately — the workflow page connects to the SSE stream
    router.push(`/workflow?prompt=${encodeURIComponent(prompt)}`);
  };

  return (
    <main className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden">
      {/* Background layers */}
      <AuroraBackground />
      <ParticleField />

      <Link
        href="/dashboard"
        className="absolute top-5 right-6 z-20 rounded-lg border border-border-subtle bg-elevated/70 px-3 py-1.5 text-xs font-mono text-text-secondary hover:text-cyan hover:border-cyan/30 transition-colors"
      >
        Dashboard →
      </Link>

      {/* Content */}
      <div className="relative z-10 w-full px-6 flex flex-col items-center justify-center min-h-screen">
        <AnimatePresence mode="wait">
          {!isLoading ? (
            <motion.div
              key="input"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -50, scale: 0.95 }}
              transition={{ duration: 0.5 }}
              className="flex flex-col items-center gap-12 w-full"
            >
              <HeroSection />
              <div className="flex rounded-full border border-border-subtle bg-elevated/50 p-1 text-xs font-mono">
                {([
                  ["resume", "Upload resume"],
                  ["prompt", "Type a prompt"],
                ] as const).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setMode(key)}
                    className={
                      mode === key
                        ? "rounded-full bg-cyan/10 px-4 py-1.5 text-cyan"
                        : "rounded-full px-4 py-1.5 text-text-muted hover:text-text-primary"
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
              {mode === "resume" ? (
                <ResumeUpload onSubmit={handleSubmit} isLoading={isLoading} />
              ) : (
                <PromptInput onSubmit={handleSubmit} isLoading={isLoading} />
              )}
            </motion.div>
          ) : (
            <motion.div
              key="loading"
              initial={{ opacity: 0, scale: 1.1 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center gap-6"
            >
              <div className="flex items-center gap-4">
                {["Plan", "Discover", "Extract", "Critic", "Validate"].map(
                  (step, i) => (
                    <motion.div
                      key={step}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.1 }}
                      className="flex items-center gap-2"
                    >
                      <div className="h-8 w-8 rounded-lg bg-card-solid border border-border-subtle flex items-center justify-center">
                        <motion.div
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{
                            duration: 1.5,
                            repeat: Infinity,
                            delay: i * 0.2,
                          }}
                          className="h-2 w-2 rounded-full bg-cyan"
                        />
                      </div>
                      <span className="text-xs font-mono text-text-muted hidden md:block">
                        {step}
                      </span>
                    </motion.div>
                  )
                )}
              </div>
              <p className="text-sm text-text-secondary animate-pulse">
                Running pipeline...
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </main>
  );
}
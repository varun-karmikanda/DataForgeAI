"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const EXAMPLE_PROMPTS = [
  "Find sponsorship opportunities for college tech fests in Karnataka with contact emails",
  "Collect pricing data for SaaS project management tools",
  "Find AI startups in India that raised seed funding in 2025, with founders and website",
  "Find freshers Java developer jobs in Bangalore",
];

interface PromptInputProps {
  onSubmit: (prompt: string) => void;
  isLoading?: boolean;
}

export function PromptInput({ onSubmit, isLoading = false }: PromptInputProps) {
  const [prompt, setPrompt] = useState("");
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [displayedPlaceholder, setDisplayedPlaceholder] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const typingTimeoutRef = useRef<NodeJS.Timeout>(undefined);

  // Typewriter effect for placeholder
  useEffect(() => {
    if (isFocused || prompt.length > 0) return;

    const target = EXAMPLE_PROMPTS[placeholderIndex];
    let charIndex = 0;

    const typeChar = () => {
      if (charIndex <= target.length) {
        setDisplayedPlaceholder(target.slice(0, charIndex));
        charIndex++;
        typingTimeoutRef.current = setTimeout(typeChar, 30 + Math.random() * 40);
      } else {
        typingTimeoutRef.current = setTimeout(() => {
          let eraseIndex = target.length;
          const eraseChar = () => {
            if (eraseIndex >= 0) {
              setDisplayedPlaceholder(target.slice(0, eraseIndex));
              eraseIndex--;
              typingTimeoutRef.current = setTimeout(eraseChar, 15);
            } else {
              setPlaceholderIndex((prev) => (prev + 1) % EXAMPLE_PROMPTS.length);
            }
          };
          eraseChar();
        }, 3000);
      }
    };

    typeChar();
    return () => clearTimeout(typingTimeoutRef.current);
  }, [placeholderIndex, isFocused, prompt.length]);

  const handleSubmit = () => {
    if (prompt.trim() && !isLoading) {
      onSubmit(prompt.trim());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        className="relative"
      >
        {/* Animated glow behind input */}
        <motion.div
          className="absolute -inset-2 rounded-3xl blur-2xl"
          animate={{
            opacity: isFocused ? 0.4 : 0.08,
            background: isFocused
              ? "linear-gradient(135deg, rgba(0,240,255,0.3), rgba(139,92,246,0.3))"
              : "linear-gradient(135deg, rgba(0,240,255,0.1), rgba(139,92,246,0.1))",
          }}
          transition={{ duration: 0.6 }}
        />

        {/* Input container */}
        <div
          className={cn(
            "relative rounded-2xl transition-all duration-500",
            "bg-card-solid border",
            isFocused
              ? "border-cyan/40 shadow-[0_0_40px_rgba(0,240,255,0.12)]"
              : "border-border-subtle hover:border-border-glow/50"
          )}
        >
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            onKeyDown={handleKeyDown}
            placeholder={isFocused ? "Describe what data you need..." : displayedPlaceholder}
            rows={4}
            className={cn(
              "w-full bg-transparent px-6 py-5 pr-16",
              "text-text-primary text-lg font-body",
              "placeholder:text-text-muted/50",
              "resize-none outline-none",
              "rounded-2xl"
            )}
          />

          {/* Submit button — bigger, magnetic */}
          <div className="absolute right-5 bottom-5">
            <motion.button
              onClick={handleSubmit}
              disabled={!prompt.trim() || isLoading}
              whileHover={{ scale: prompt.trim() ? 1.1 : 1 }}
              whileTap={{ scale: 0.9 }}
              className={cn(
                "flex h-12 w-12 items-center justify-center rounded-xl",
                "transition-all duration-300",
                prompt.trim() && !isLoading
                  ? "bg-gradient-to-br from-cyan to-violet text-void shadow-lg shadow-cyan/30"
                  : "bg-elevated text-text-muted border border-border-subtle"
              )}
            >
              <AnimatePresence mode="wait">
                {isLoading ? (
                  <motion.div
                    key="loading"
                    initial={{ opacity: 0, rotate: 0 }}
                    animate={{ opacity: 1, rotate: 360 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                  >
                    <Loader2 className="h-5 w-5" />
                  </motion.div>
                ) : (
                  <motion.div
                    key="arrow"
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -5 }}
                    transition={{ duration: 0.3 }}
                  >
                    <ArrowUp className="h-5 w-5" strokeWidth={2.5} />
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.button>
          </div>
        </div>

        {/* Keyboard hints */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1, duration: 0.5 }}
          className="mt-4 text-center text-xs text-text-muted"
        >
          Press{" "}
          <kbd className="px-1.5 py-0.5 rounded border border-border-subtle bg-elevated text-text-secondary text-[10px] font-mono">
            Enter
          </kbd>{" "}
          to run &middot;{" "}
          <kbd className="px-1.5 py-0.5 rounded border border-border-subtle bg-elevated text-text-secondary text-[10px] font-mono">
            Shift+Enter
          </kbd>{" "}
          for new line
        </motion.p>
      </motion.div>

      {/* Example chips */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, duration: 0.6 }}
        className="mt-8 flex flex-wrap justify-center gap-2.5"
      >
        {EXAMPLE_PROMPTS.map((example, i) => (
          <motion.button
            key={i}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.5 + i * 0.1 }}
            whileHover={{ scale: 1.03, y: -2 }}
            whileTap={{ scale: 0.97 }}
            onClick={() => {
              setPrompt(example);
              textareaRef.current?.focus();
            }}
            className={cn(
              "group flex items-center gap-2 px-4 py-2.5 rounded-full",
              "bg-elevated/50 border border-border-subtle",
              "text-sm text-text-secondary",
              "hover:border-cyan/30 hover:text-cyan hover:bg-cyan/5",
              "transition-all duration-300"
            )}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan/40 group-hover:bg-cyan transition-colors" />
            <span className="max-w-[280px] truncate">{example}</span>
          </motion.button>
        ))}
      </motion.div>
    </div>
  );
}

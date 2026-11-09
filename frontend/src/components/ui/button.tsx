import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { twMerge } from "tailwind-merge";

const buttonVariants = cva("button", {
  variants: { variant: { default: "button-primary", outline: "button-outline", ghost: "button-ghost", danger: "button-danger" },
    size: { default: "", sm: "button-sm", icon: "button-icon" } },
  defaultVariants: { variant: "default", size: "default" },
});

export function Button({ className, variant, size, asChild = false, ...props }:
  React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Element = asChild ? Slot : "button";
  return <Element className={twMerge(buttonVariants({ variant, size, className }))} {...props} />;
}

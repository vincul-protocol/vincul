import { useRef, useLayoutEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  anchorEl: HTMLElement | null;
  open: boolean;
  onClose: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  children: ReactNode;
}

export default function Popover({ anchorEl, open, onClose, onMouseEnter, onMouseLeave, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => {
    if (!open || !anchorEl) return;

    const update = () => {
      const anchor = anchorEl.getBoundingClientRect();
      const popover = popoverRef.current;
      if (!popover) return;

      const pw = popover.offsetWidth;
      const ph = popover.offsetHeight;
      const gap = 8;

      // Default: below, centered
      let top = anchor.bottom + gap;
      let left = anchor.left + anchor.width / 2 - pw / 2;

      // Flip above if no space below
      if (top + ph > window.innerHeight - 8) {
        top = anchor.top - ph - gap;
      }

      // Shift horizontal if near edges
      if (left < 8) left = 8;
      if (left + pw > window.innerWidth - 8) {
        left = window.innerWidth - pw - 8;
      }

      setPos({ top, left });
    };

    // Run after render so popover dimensions are available
    requestAnimationFrame(update);
  }, [open, anchorEl]);

  // Click outside
  useLayoutEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current && !popoverRef.current.contains(target) &&
        anchorEl && !anchorEl.contains(target)
      ) {
        onClose();
      }
    };
    // Delay to avoid closing on the same click that opened
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClick);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [open, anchorEl, onClose]);

  if (!open || !anchorEl) return null;

  return createPortal(
    <div
      ref={popoverRef}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 60 }}
      className="bg-gray-800 border border-gray-700 rounded-lg shadow-xl max-w-sm"
    >
      {children}
    </div>,
    document.body,
  );
}

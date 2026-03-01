import { useState, useRef, useCallback, useEffect } from 'react';

interface PopoverState {
  anchorEl: HTMLElement | null;
  activeId: string | null;
  pinned: boolean;
}

export function usePopover() {
  const [state, setState] = useState<PopoverState>({
    anchorEl: null,
    activeId: null,
    pinned: false,
  });

  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const leaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimers = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    if (leaveTimerRef.current) {
      clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
  }, []);

  const onMouseEnter = useCallback((id: string, el: HTMLElement) => {
    clearTimers();
    hoverTimerRef.current = setTimeout(() => {
      setState((prev) => {
        if (prev.pinned) return prev;
        return { anchorEl: el, activeId: id, pinned: false };
      });
    }, 200);
  }, [clearTimers]);

  const onMouseLeave = useCallback(() => {
    clearTimers();
    leaveTimerRef.current = setTimeout(() => {
      setState((prev) => {
        if (prev.pinned) return prev;
        return { anchorEl: null, activeId: null, pinned: false };
      });
    }, 300);
  }, [clearTimers]);

  const onPopoverMouseEnter = useCallback(() => {
    if (leaveTimerRef.current) {
      clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
  }, []);

  const onPopoverMouseLeave = useCallback(() => {
    setState((prev) => {
      if (prev.pinned) return prev;
      return { anchorEl: null, activeId: null, pinned: false };
    });
  }, []);

  const onClick = useCallback((id: string, el: HTMLElement) => {
    clearTimers();
    setState((prev) => {
      if (prev.activeId === id && prev.pinned) {
        return { anchorEl: null, activeId: null, pinned: false };
      }
      return { anchorEl: el, activeId: id, pinned: true };
    });
  }, [clearTimers]);

  const onClose = useCallback(() => {
    clearTimers();
    setState({ anchorEl: null, activeId: null, pinned: false });
  }, [clearTimers]);

  // Escape key handler
  useEffect(() => {
    if (!state.activeId) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [state.activeId, onClose]);

  // Cleanup timers on unmount
  useEffect(() => clearTimers, [clearTimers]);

  return {
    state,
    handlers: {
      onMouseEnter,
      onMouseLeave,
      onPopoverMouseEnter,
      onPopoverMouseLeave,
      onClick,
      onClose,
    },
  };
}

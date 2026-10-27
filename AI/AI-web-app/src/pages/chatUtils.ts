interface Message {
  text: string;
  sender: "user" | "response";
}

export const scrollParentToBottom = (el: HTMLDivElement | null) => {
  if (!el) return;
  const parent = el.parentElement;
  if (!parent) return;

  const paddingBottom = parseInt(
    getComputedStyle(parent).paddingBottom || "0",
    10
  );

  parent.scrollTo({
    top: parent.scrollHeight - paddingBottom,
    behavior: "smooth",
  });
};

// Empty text renders as the typing dots; the first streamed piece replaces it.
export const createLoadingMessage = (): Message => ({
  text: "",
  sender: "response",
});

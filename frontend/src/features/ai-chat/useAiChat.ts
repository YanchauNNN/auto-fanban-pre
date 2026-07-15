import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ApiAdapter } from "../../platform/api/types";
import type {
  AiConversationDetail,
  AiMessage,
  AiSendMessageResult,
  SendAiMessagePayload,
} from "./types";

const SELECTED_CONVERSATION_KEY = "fanban.ai.selectedConversationId";

type OptimisticExchangeStatus = "thinking" | "cancelled" | "failed";

type OptimisticExchange = {
  requestId: string;
  conversationId: string;
  userMessage: AiMessage;
  status: OptimisticExchangeStatus;
};

type SendMessageVariables = {
  conversationId: string;
  payload: SendAiMessagePayload;
  signal: AbortSignal;
  requestId: string;
};

type ActiveRequest = {
  controller: AbortController;
  requestId: string;
};

export function useAiChat(adapter: ApiAdapter, enabled: boolean) {
  const queryClient = useQueryClient();
  const activeRequestRef = useRef<ActiveRequest | null>(null);
  const visibleRequestIdRef = useRef<string | null>(null);
  const [invalidConversationIds, setInvalidConversationIds] = useState<Set<string>>(
    () => new Set<string>(),
  );
  const [selectedConversationId, setSelectedConversationId] = useState(() =>
    typeof window === "undefined"
      ? ""
      : window.localStorage.getItem(SELECTED_CONVERSATION_KEY) ?? "",
  );
  const [optimisticExchange, setOptimisticExchange] = useState<OptimisticExchange | null>(null);
  const [isSendCancelled, setIsSendCancelled] = useState(false);

  const stateQuery = useQuery({
    queryKey: ["ai-chat", "state"],
    queryFn: ({ signal }) => adapter.getAiState(signal),
    enabled,
    staleTime: 30000,
    retry: false,
  });

  const conversationsQuery = useQuery({
    queryKey: ["ai-chat", "conversations"],
    queryFn: ({ signal }) => adapter.listAiConversations(signal),
    enabled: enabled && Boolean(stateQuery.data?.enabled),
    staleTime: 10000,
    retry: false,
  });

  const availableConversations = useMemo(
    () =>
      (conversationsQuery.data ?? []).filter(
        (conversation) => !invalidConversationIds.has(conversation.conversationId),
      ),
    [conversationsQuery.data, invalidConversationIds],
  );

  const selectedConversationAvailable = useMemo(
    () =>
      Boolean(
        selectedConversationId &&
          availableConversations.some(
            (conversation) => conversation.conversationId === selectedConversationId,
          ),
      ),
    [availableConversations, selectedConversationId],
  );

  useEffect(() => {
    if (!enabled || !conversationsQuery.isSuccess) {
      return;
    }
    if (availableConversations.length === 0) {
      if (selectedConversationId) {
        setSelectedConversationId("");
      }
      return;
    }
    if (!selectedConversationId || !selectedConversationAvailable) {
      setSelectedConversationId(availableConversations[0].conversationId);
    }
  }, [
    availableConversations,
    conversationsQuery.isSuccess,
    enabled,
    selectedConversationAvailable,
    selectedConversationId,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (selectedConversationId) {
      window.localStorage.setItem(SELECTED_CONVERSATION_KEY, selectedConversationId);
    } else {
      window.localStorage.removeItem(SELECTED_CONVERSATION_KEY);
    }
  }, [selectedConversationId]);

  useEffect(() => {
    setOptimisticExchange((current) =>
      current?.conversationId === selectedConversationId ? current : null,
    );
  }, [selectedConversationId]);

  useEffect(
    () => () => {
      activeRequestRef.current?.controller.abort();
    },
    [],
  );

  const conversationQuery = useQuery({
    queryKey: ["ai-chat", "conversation", selectedConversationId],
    queryFn: ({ signal }) => adapter.getAiConversation(selectedConversationId, signal),
    enabled:
      enabled &&
      selectedConversationAvailable &&
      Boolean(selectedConversationId) &&
      Boolean(stateQuery.data?.enabled),
    retry: false,
  });

  useEffect(() => {
    if (!selectedConversationId || !isAiConversationNotFoundError(conversationQuery.error)) {
      return;
    }
    markConversationInvalid(selectedConversationId);
    queryClient.removeQueries({
      queryKey: ["ai-chat", "conversation", selectedConversationId],
      exact: true,
    });
    setSelectedConversationId("");
    void queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
  }, [conversationQuery.error, queryClient, selectedConversationId]);

  const createConversationMutation = useMutation({
    mutationFn: (title?: string) => adapter.createAiConversation(title),
    onSuccess: async (conversation) => {
      queryClient.setQueryData(
        ["ai-chat", "conversations"],
        (current: Awaited<ReturnType<ApiAdapter["listAiConversations"]>> | undefined) => [
          conversation,
          ...(current ?? []).filter((item) => item.conversationId !== conversation.conversationId),
        ],
      );
      setSelectedConversationId(conversation.conversationId);
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
  });

  const clearConversationMutation = useMutation({
    mutationFn: (conversationId: string) => adapter.clearAiConversation(conversationId),
    onSuccess: async (_result, conversationId) => {
      queryClient.setQueryData<AiConversationDetail | undefined>(
        ["ai-chat", "conversation", conversationId],
        (current) => (current ? { ...current, messages: [], messageCount: 0 } : current),
      );
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
  });

  const renameConversationMutation = useMutation({
    mutationFn: ({
      conversationId,
      title,
    }: {
      conversationId: string;
      title: string;
    }) => adapter.renameAiConversation(conversationId, title),
    onSuccess: (renamed) => {
      queryClient.setQueryData(
        ["ai-chat", "conversations"],
        (current: Awaited<ReturnType<ApiAdapter["listAiConversations"]>> | undefined) =>
          (current ?? []).map((item) =>
            item.conversationId === renamed.conversationId ? { ...item, ...renamed } : item,
          ),
      );
      queryClient.setQueryData<AiConversationDetail | undefined>(
        ["ai-chat", "conversation", renamed.conversationId],
        (current) => (current ? { ...current, ...renamed } : current),
      );
    },
  });

  const sendMessageMutation = useMutation({
    mutationFn: ({ conversationId, payload, signal }: SendMessageVariables) =>
      adapter.sendAiMessage(conversationId, payload, signal),
    onMutate: (variables) => {
      visibleRequestIdRef.current = variables.requestId;
      setIsSendCancelled(false);
      setOptimisticExchange({
        requestId: variables.requestId,
        conversationId: variables.conversationId,
        userMessage: {
          messageId: `local-user-${variables.requestId}`,
          role: "user",
          content: variables.payload.content,
          createdAt: new Date().toISOString(),
          metadata: { status: "pending", local: true },
        },
        status: "thinking",
      });
    },
    onSuccess: (result, variables) => {
      if (variables.signal.aborted) {
        return;
      }
      if (visibleRequestIdRef.current === variables.requestId) {
        visibleRequestIdRef.current = null;
      }
      setOptimisticExchange((current) =>
        current?.requestId === variables.requestId ? null : current,
      );
      appendExchange(queryClient, variables.conversationId, result);
      void queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
    onError: async (error, variables) => {
      const cancelled = isAbortError(error);
      if (cancelled) {
        return;
      }
      if (isAiConversationNotFoundError(error)) {
        markConversationInvalid(variables.conversationId);
        setOptimisticExchange((current) =>
          current?.requestId === variables.requestId ? null : current,
        );
        if (selectedConversationId === variables.conversationId) {
          setSelectedConversationId("");
        }
        await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
        return;
      }
      if (visibleRequestIdRef.current === variables.requestId) {
        setIsSendCancelled(false);
        setOptimisticExchange((current) =>
          current?.requestId === variables.requestId ? { ...current, status: "failed" } : current,
        );
      }
      await queryClient.invalidateQueries({
        queryKey: ["ai-chat", "conversation", variables.conversationId],
      });
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
    onSettled: (_result, _error, variables) => {
      if (activeRequestRef.current?.requestId === variables.requestId) {
        activeRequestRef.current = null;
      }
    },
  });

  const deleteConversationMutation = useMutation({
    mutationFn: (conversationId: string) => {
      if (!adapter.deleteAiConversation) {
        return Promise.reject(new Error("当前 AI 服务不支持删除会话。"));
      }
      return adapter.deleteAiConversation(conversationId);
    },
    onSuccess: async (_result, conversationId) => {
      markConversationInvalid(conversationId);
      queryClient.removeQueries({
        queryKey: ["ai-chat", "conversation", conversationId],
        exact: true,
      });
      queryClient.setQueryData(
        ["ai-chat", "conversations"],
        (current: Awaited<ReturnType<ApiAdapter["listAiConversations"]>> | undefined) =>
          (current ?? []).filter((item) => item.conversationId !== conversationId),
      );
      if (selectedConversationId === conversationId) {
        setSelectedConversationId("");
      }
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
    onError: async (error, conversationId) => {
      if (!isAiConversationNotFoundError(error)) {
        return;
      }
      markConversationInvalid(conversationId);
      if (selectedConversationId === conversationId) {
        setSelectedConversationId("");
      }
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
  });

  function sendMessage({
    conversationId,
    payload,
  }: Omit<SendMessageVariables, "signal" | "requestId">) {
    const controller = new AbortController();
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    activeRequestRef.current = { controller, requestId };
    return sendMessageMutation.mutateAsync({
      conversationId,
      payload,
      signal: controller.signal,
      requestId,
    });
  }

  function markConversationInvalid(conversationId: string) {
    setInvalidConversationIds((current) => {
      if (current.has(conversationId)) {
        return current;
      }
      return new Set(current).add(conversationId);
    });
  }

  function cancelSendMessage() {
    const activeRequest = activeRequestRef.current;
    if (!activeRequest) {
      return;
    }
    setIsSendCancelled(true);
    setOptimisticExchange((current) =>
      current?.requestId === activeRequest.requestId ? { ...current, status: "cancelled" } : current,
    );
    visibleRequestIdRef.current = null;
    activeRequestRef.current = null;
    activeRequest.controller.abort();
    sendMessageMutation.reset();
  }

  return {
    stateQuery,
    conversationsQuery,
    availableConversations,
    conversationQuery,
    selectedConversationId,
    setSelectedConversationId,
    createConversationMutation,
    clearConversationMutation,
    deleteConversationMutation,
    renameConversationMutation,
    sendMessageMutation,
    sendMessage,
    cancelSendMessage,
    optimisticExchange,
    isSendCancelled,
  };
}

function isAbortError(error: unknown) {
  return typeof DOMException !== "undefined" && error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

export function isAiConversationNotFoundError(error: unknown) {
  if (!error || typeof error !== "object") {
    return false;
  }
  const value = error as {
    status?: unknown;
    detail?: unknown;
    message?: unknown;
  };
  if (value.status !== 404) {
    return false;
  }
  const detail = value.detail;
  if (detail === "conversation_not_found" || value.message === "conversation_not_found") {
    return true;
  }
  return Boolean(
    detail &&
      typeof detail === "object" &&
      ((detail as { code?: unknown }).code === "conversation_not_found" ||
        (detail as { message?: unknown }).message === "conversation_not_found"),
  );
}

function appendExchange(
  queryClient: ReturnType<typeof useQueryClient>,
  conversationId: string,
  result: AiSendMessageResult,
) {
  queryClient.setQueryData<AiConversationDetail | undefined>(
    ["ai-chat", "conversation", conversationId],
    (current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        updatedAt: result.assistantMessage.createdAt || current.updatedAt,
        messageCount: current.messageCount + 2,
        messages: [...current.messages, result.userMessage, result.assistantMessage],
      };
    },
  );
}

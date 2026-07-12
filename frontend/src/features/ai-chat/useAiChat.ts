import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { ApiAdapter } from "../../platform/api/types";
import type {
  AiConversationDetail,
  AiSendMessageResult,
  SendAiMessagePayload,
} from "./types";

const SELECTED_CONVERSATION_KEY = "fanban.ai.selectedConversationId";

export function useAiChat(adapter: ApiAdapter, enabled: boolean) {
  const queryClient = useQueryClient();
  const [selectedConversationId, setSelectedConversationId] = useState(() =>
    typeof window === "undefined"
      ? ""
      : window.localStorage.getItem(SELECTED_CONVERSATION_KEY) ?? "",
  );

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

  const selectedConversationAvailable = useMemo(
    () =>
      Boolean(
        selectedConversationId &&
          conversationsQuery.data?.some(
            (conversation) => conversation.conversationId === selectedConversationId,
          ),
      ),
    [conversationsQuery.data, selectedConversationId],
  );

  useEffect(() => {
    if (!enabled || !conversationsQuery.isSuccess) {
      return;
    }
    if (conversationsQuery.data.length === 0) {
      if (selectedConversationId) {
        setSelectedConversationId("");
      }
      return;
    }
    if (!selectedConversationId || !selectedConversationAvailable) {
      setSelectedConversationId(conversationsQuery.data[0].conversationId);
    }
  }, [
    conversationsQuery.data,
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
    mutationFn: ({
      conversationId,
      payload,
    }: {
      conversationId: string;
      payload: SendAiMessagePayload;
    }) => adapter.sendAiMessage(conversationId, payload),
    onSuccess: (result, variables) => {
      appendExchange(queryClient, variables.conversationId, result);
      void queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
    onError: async (_error, variables) => {
      await queryClient.invalidateQueries({
        queryKey: ["ai-chat", "conversation", variables.conversationId],
      });
      await queryClient.invalidateQueries({ queryKey: ["ai-chat", "conversations"] });
    },
  });

  return {
    stateQuery,
    conversationsQuery,
    conversationQuery,
    selectedConversationId,
    setSelectedConversationId,
    createConversationMutation,
    clearConversationMutation,
    renameConversationMutation,
    sendMessageMutation,
  };
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

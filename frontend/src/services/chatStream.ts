import { buildChatCompletionPayload, CHAT_COMPLETIONS_PATH } from '@/services/chatCompletions';
import { buildAuthHeaders, handleUnauthorized, OPENAI_COMPAT_BASE_URL } from '@/services/http';

export interface StreamChunk {
  content?: string;
  vidmuse?: {
    requires_confirmation: boolean;
    pending_decision_id: string | null;
    decision_options: any[];
  };
}

export const streamMessage = async (
  projectId: string,
  message: string,
  onChunk: (chunk: string) => void,
  onDone: (vidmuseData: any) => void,
  onError: (error: any) => void,
  sessionId?: string
) => {
  try {
    const response = await fetch(`${OPENAI_COMPAT_BASE_URL}${CHAT_COMPLETIONS_PATH}`, {
      method: 'POST',
      headers: buildAuthHeaders(),
      body: JSON.stringify(buildChatCompletionPayload(projectId, message, true, sessionId)),
    });

    if (response.status === 401) {
      handleUnauthorized();
      throw new Error('Unauthorized');
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `HTTP error! status: ${response.status}`);
    }

    if (!response.body) throw new Error('Response body is null');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let vidmuseData = null;
    // 跨 chunk 行缓冲：TCP 可能将一行 SSE 数据拆成多个 chunk 送达
    let lineBuffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      lineBuffer += decoder.decode(value, { stream: true });
      const lines = lineBuffer.split('\n');
      // 最后一段可能是不完整的行，留在 buffer 中等待下一个 chunk
      lineBuffer = lines.pop() ?? '';
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6).trim();
          if (dataStr === '[DONE]') continue;
          if (!dataStr) continue;

          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.choices && parsed.choices.length > 0) {
              const delta = parsed.choices[0].delta;
              if (delta && delta.content) {
                onChunk(delta.content);
              }
            }
            
            // Extract vidmuse extension data if present
            if (parsed.vidmuse) {
              vidmuseData = parsed.vidmuse;
            }
          } catch (e) {
            console.error('Error parsing streaming chunk:', e, dataStr);
          }
        }
      }
    }
    
    onDone(vidmuseData);
  } catch (error) {
    onError(error);
  }
};

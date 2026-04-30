export const CHAT_COMPLETIONS_PATH = '/chat/completions';
const CHAT_MODEL = 'vidmuse-director';

export const buildChatCompletionPayload = (
  projectId: string,
  message: string,
  stream: boolean,
  sessionId?: string
) => ({
  model: CHAT_MODEL,
  messages: [{ role: 'user', content: message }],
  project_id: projectId,
  session_id: sessionId,
  stream,
});

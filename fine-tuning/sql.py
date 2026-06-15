FINE_TUNING_REQ = """
                    SELECT
                        u.content AS input,
                        b.generated_sql AS label
                    FROM message u
                    JOIN LATERAL (
                        SELECT generated_sql, sql_status, feedback
                        FROM message
                        WHERE conversation_id = u.conversation_id
                        AND sender_role = 'bot'
                        AND created_at > u.created_at
                        ORDER BY created_at ASC
                        LIMIT 1
                    ) b ON true
                    WHERE u.sender_role = 'user'
                    AND u.intention = 'recherche'
                    AND b.generated_sql IS NOT NULL
                    AND b.feedback = 'like';
                """
IDENTIFICATION_FINE_TUNING_REQ = """
                                    SELECT
                                        u.content AS input,
                                        u.intention AS label
                                    FROM message u
                                    WHERE u.sender_role = 'user'
                                    AND u.intention IS NOT NULL
                                    AND u.feedback = 'like';
                                """
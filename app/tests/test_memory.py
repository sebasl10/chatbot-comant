from app.services.memory import add_memory, search_memory, get_all_memories, delete_memories, close_memory


def main():
    """ add_memory("Je m'appelle Sebastian", "test")
    memory = search_memory("Comment je m'appelle?", "test")
    print(memory) """

    memories = get_all_memories(str(5))
    print()
    for memory in memories:
        print(memory)
        print()
    
    #delete_memories(5)

if __name__ == "__main__":
    try:
        main()
    finally:
        close_memory()
lock-all:
	./scripts/lock.sh extract-core
	./scripts/lock.sh extract-python

lock-dist:
	./scripts/lock.sh ${project}

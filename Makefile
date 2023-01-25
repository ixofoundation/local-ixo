start:
	docker-compose up -d

startwl: 
	docker-compose up -d
	docker logs ixod --follow

down:
	docker-compose down
clean:
	docker-compose -f docker-compose.yaml -f docker-compose.clean.yaml up -d
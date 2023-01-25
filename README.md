# IXO-1
![banner](banner.png)

## Requirements
- make
- docker
- docker-compose

## How to use 

Clone repo and cd
```
https://github.com/ixofoundation/local-ixo
cd local-ixo
```

Start with
```
make start
```
Or with logs
```
make startwl
```
Remove container
```
make down
```
Remove data
```
make clean 
```

## Run without make

Start
```
docker-compose up -d
```
Start with logs
```
docker-compose up -d
docker logs ixod --follow
```
Remove container
```
docker-compose down
```
Remove data
```
docker-compose -f docker-compose.yaml -f docker-compose.clean.yaml up -d
```
## Network related info
- Chain_id  **ixo-1**
- Voting period set to 5 mintues

## Usable mnemonics
- validator
```ixo1gvrc2naj4ck956j4s87mfxv478zvuprhqy7rcv```
```
pen ozone timber damage crash gym attack siren memory wheat exhaust attract cloth ordinary knock jelly couple bench man scale render torch ostrich mistake
```
- ```ixo130d95u3cgknlpkuatu50gpr7tq028mwtt3ns4x```
```
foster erupt gauge window best isolate lake young vibrant during spring put february fish ladder pact guard biology buffalo birth diagram gauge rival solid
```
- ```ixo1xkwnm5kc63vfnr974g5rysxcu89g2kx9lw5942```
```
render clutch aspect drill buffalo habit field chief approve tenant oppose scissors multiply hover project device negative property curtain utility impose entry horn goddess
```
- ```ixo14dz467czznhryc7mkzhcknx48v4dfnt5eupyyu```
```
unknown wife pepper detail bird drink slide flip talk drop umbrella pioneer define morning ripple hedgehog ankle inmate basic trouble forget note vacant smooth
```
- ```ixo14rckcxrrtcqz9kzj4nrvghhwn49rukc0rfjavp```
```
jeans direct donkey capital differ source thunder exist inspire urge order trust aisle cabin rocket rescue patrol minimum such all camp night fold anger
```
.PHONY: restore build test format run demo loadtest migration clean

restore:
	dotnet restore

build: restore
	dotnet build --no-restore -c Release -warnaserror

test: build
	dotnet test --no-build -c Release

format:
	dotnet format

run:
	dotnet run --project src/StockReservation.Api --urls http://localhost:5080

demo:
	./scripts/demo.sh

loadtest:
	dotnet run -c Release --project src/StockReservation.LoadTest -- 3000 32 600

# Requires the EF Core CLI: dotnet tool install --global dotnet-ef --version 10.0.12
migration:
	dotnet ef migrations add $(NAME) --project src/StockReservation.Application \
		--startup-project src/StockReservation.Api --output-dir Persistence/Migrations

clean:
	dotnet clean && rm -f src/StockReservation.Api/stock.db*
